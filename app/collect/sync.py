"""LangFuse 트레이스를 로컬에 **누적 저장**하고, 두 번째부터는 **증분만** 내려받는다.

정본은 두 파일이다.

- `data/collection.json` — 지금까지 수집한 모든 트레이스 요약(최신순, `id` 유일).
  한 번 저장한 행은 지우지 않는다. 재수집은 교체가 아니라 병합이다.
- `data/collection.state.json` — 동기화 커서. **연속으로 훑은 구간의 끝**(`last_timestamp`)·
  마지막 동기화 시각·저장 건수를 담는다.

수집 대상은 항상 프로젝트의 **전체 트레이스**다. 조회 필터(name·user_id)는 두지 않는다.
필터가 있으면 커서가 어떤 범위를 훑은 것인지 달라져서, 필터를 바꿀 때마다 전체를 다시 받아야
하고 저장된 로그의 의미도 흐려진다.

동기화는 항상 **timestamp 오름차순**으로 페이지를 훑는다. 오름차순이면 조회 중에 새 로그가
들어와도 이미 본 페이지가 밀리지 않고, 중간에 멈춰도 `last_timestamp` 가 안전한 워터마크가
되어 다음 실행이 그 지점부터 이어받는다. `from_timestamp` 는 경계 포함이라 마지막 트레이스를
한 번 더 받지만 `id` 기준 병합이 중복을 흡수한다.

커서는 **이번 훑기에서 실제로 받은 행**의 최신 시각으로만 전진한다. 저장된 행 전체의 최대
시각을 쓰면 안 된다 — 예전에 최신 구간만 담아둔 스냅샷이 남아 있는 상태에서 백필이 중간에
끊기면 커서가 그 최신 시각으로 튀어, 아직 못 받은 중간 구간이 영영 건너뛰어진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.langfuse_client import list_traces, trace_summary
from app.storage import store
from app.storage.paths import collection_file, collection_state_file

PAGE_SIZE = 100
"""한 번의 API 호출로 받는 트레이스 수(LangFuse 페이지 크기)."""

LIST_FIELDS = "core,io,metrics"
"""목록 조회에 필요한 필드 그룹만 받는다. taskId 는 ``io``(=trace.input), latency·total_cost 는
``metrics`` 에서 온다. 관측치·스코어는 저장 스키마에 쓰지 않으므로 제외해 응답을 가볍게 한다."""

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


def task_id_of(trace: Any) -> str | None:
    """트레이스에서 도메인 taskId 를 뽑는다. LangFuse 는 이 값을 `trace.input` 에만 담는다."""
    raw = getattr(trace, "input", None)
    if not isinstance(raw, dict):
        return None
    value = raw.get("taskId") or (raw.get("request") or {}).get("taskId")
    return str(value) if value else None


def row_of(trace: Any) -> dict[str, Any]:
    """저장 스냅샷 한 줄. 대시보드·Task 리뷰·테스트 데이터가 함께 쓰는 형태."""
    summary = trace_summary(trace)
    timestamp = summary.get("timestamp")
    return {
        "id": summary.get("id"),
        "taskId": task_id_of(trace),
        "name": summary.get("name"),
        "timestamp": str(timestamp) if timestamp is not None else None,
        "user_id": summary.get("user_id"),
        "latency": summary.get("latency"),
        "total_cost": summary.get("total_cost"),
    }


def parse_timestamp(value: Any) -> datetime | None:
    """저장된 timestamp 문자열을 datetime 으로. 못 읽으면 None(정렬에서 맨 뒤로)."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def load_rows() -> list[dict[str, Any]]:
    """누적 저장된 트레이스 요약(최신순). 없거나 깨졌으면 빈 리스트."""
    rows = store.load_json(collection_file())
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def load_state() -> dict[str, Any]:
    """동기화 커서. 아직 한 번도 수집하지 않았으면 빈 dict."""
    state = store.load_json(collection_state_file())
    return state if isinstance(state, dict) else {}


def needs_backfill(state: dict[str, Any]) -> bool:
    """커서가 없으면 처음부터 전체를 훑어야 한다."""
    return not state.get("backfilled") or not state.get("last_timestamp")


@dataclass(frozen=True)
class SyncResult:
    """한 번의 동기화 결과."""

    mode: str
    """`"backfill"`(처음부터 전체) 또는 `"incremental"`(커서 이후만)."""

    added: int
    updated: int
    total: int
    """병합 후 저장된 전체 로그 수."""

    fetched: int
    """이번에 LangFuse 에서 받은 행 수(중복 포함)."""

    pages: int
    completed: bool
    """마지막 페이지까지 갔으면 True. `max_pages` 로 끊겼으면 False."""


def sync(
    *,
    full: bool = False,
    page_size: int = PAGE_SIZE,
    max_pages: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> SyncResult:
    """LangFuse 로그를 받아 누적 저장소에 병합한다.

    커서가 없거나 `full` 이면 처음부터(=쌓인 로그 전체), 아니면 마지막으로 훑은 시각 이후만
    받는다. 어느 쪽이든 기존에 저장된 행은 지우지 않는다.
    """
    state = load_state()
    backfill = full or needs_backfill(state)
    cursor = None if backfill else parse_timestamp(state.get("last_timestamp"))

    merged = {row["id"]: row for row in load_rows() if row.get("id")}
    added = updated = fetched = pages = 0
    completed = False
    page = 1
    watermark: datetime | None = None

    while max_pages is None or pages < max_pages:
        response = list_traces(
            page=page,
            limit=page_size,
            from_timestamp=cursor,
            order_by="timestamp.asc",
            fields=LIST_FIELDS,
        )
        batch = [row_of(trace) for trace in getattr(response, "data", []) or []]
        pages += 1
        fetched += len(batch)
        for row in batch:
            stamp = parse_timestamp(row.get("timestamp"))
            if stamp is not None and (watermark is None or stamp > watermark):
                watermark = stamp
            trace_id = row.get("id")
            if not trace_id:
                continue
            current = merged.get(trace_id)
            if current is None:
                added += 1
            elif current != row:
                updated += 1
            else:
                continue
            merged[trace_id] = row
        if on_progress is not None:
            on_progress(pages, fetched)

        total_pages = getattr(getattr(response, "meta", None), "total_pages", None)
        if not batch or (total_pages is not None and page >= total_pages):
            completed = True
            break
        page += 1

    rows = sorted(
        merged.values(),
        key=lambda row: parse_timestamp(row.get("timestamp")) or _OLDEST,
        reverse=True,
    )
    if added or updated or not collection_file().exists():
        store.save_json(collection_file(), rows)

    # 이번에 훑은 구간의 끝까지만 커서를 옮긴다(아무것도 못 받았으면 이전 커서 유지).
    newest = watermark if watermark is not None else cursor
    store.save_json(
        collection_state_file(),
        {
            "backfilled": bool(state.get("backfilled")) or backfill,
            "last_timestamp": newest.isoformat() if newest is not None else None,
            "last_synced_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "total": len(rows),
        },
    )
    return SyncResult(
        mode="backfill" if backfill else "incremental",
        added=added,
        updated=updated,
        total=len(rows),
        fetched=fetched,
        pages=pages,
        completed=completed,
    )
