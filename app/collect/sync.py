"""LangFuse 트레이스를 로컬에 **누적 저장**하고, 두 번째부터는 **증분만** 내려받는다.

정본은 두 파일이다.

- `data/collection.json` — 지금까지 수집한 모든 트레이스 요약(최신순, `id` 유일).
  한 번 저장한 행은 지우지 않는다. 재수집은 교체가 아니라 병합이다.
- `data/collection.state.json` — 동기화 커서. **환경(dev·prod)을 키로 나눠** 담는다.
  각 값은 **연속으로 훑은 구간의 끝**(`last_timestamp`)·마지막 동기화 시각·저장 건수다.

수집 대상은 항상 프로젝트의 **전체 트레이스**다. 조회 필터(name·user_id)는 두지 않는다.
필터가 있으면 커서가 어떤 범위를 훑은 것인지 달라져서, 필터를 바꿀 때마다 전체를 다시 받아야
하고 저장된 로그의 의미도 흐려진다.

**여러 LangFuse 프로젝트를 한 목록에 합쳐 담는다**(→ [app.environments][]). 행마다 `env` 가
붙어 어디서 온 것인지 알 수 있고, 목록은 환경과 무관하게 시간순으로 정렬된다. 트레이스 id 가
전역 유일이라 `id` 병합이 그대로 성립한다. 반면 **커서는 환경마다 따로**다 — "어디까지 훑었는지"
는 프로젝트마다 다르고, 하나로 합치면 서로를 밀어내 양쪽 다 구멍이 생긴다.

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
from typing import Any, Callable, Sequence

from app import environments
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


def row_of(trace: Any, env: str) -> dict[str, Any]:
    """저장 스냅샷 한 줄. 대시보드·Task 리뷰·테스트 데이터가 함께 쓰는 형태.

    `env` 는 이 행이 어느 LangFuse 프로젝트에서 왔는지다. 화면이 환경을 구분하는 **유일한**
    근거이므로 모든 행에 반드시 들어간다.
    """
    summary = trace_summary(trace)
    timestamp = summary.get("timestamp")
    return {
        "id": summary.get("id"),
        "env": environments.validate(env),
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
    """누적 저장된 트레이스 요약 전체(환경 구분 없이 최신순). 없거나 깨졌으면 빈 리스트."""
    rows = store.load_json(collection_file())
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def rows_of(rows: Sequence[dict[str, Any]], env: str) -> list[dict[str, Any]]:
    """그 환경에서 온 행만."""
    return [row for row in rows if environments.of(row) == env]


def load_states() -> dict[str, dict[str, Any]]:
    """환경 → 동기화 커서.

    환경 구분이 없던 시절의 평면 커서(`{"backfilled": …}`)는 `dev` 것으로 읽는다. 그때는 개발
    프로젝트 하나만 보고 있었다.
    """
    state = store.load_json(collection_state_file())
    if not isinstance(state, dict):
        return {}
    if "last_timestamp" in state or "backfilled" in state:
        return {environments.DEV: state}
    return {key: value for key, value in state.items() if isinstance(value, dict)}


def load_state(env: str) -> dict[str, Any]:
    """그 환경의 커서. 아직 한 번도 수집하지 않았으면 빈 dict."""
    return load_states().get(environments.validate(env), {})


def needs_backfill(state: dict[str, Any]) -> bool:
    """커서가 없으면 처음부터 전체를 훑어야 한다."""
    return not state.get("backfilled") or not state.get("last_timestamp")


@dataclass(frozen=True)
class SyncResult:
    """한 번의 동기화 결과(환경 하나)."""

    mode: str
    """`"backfill"`(처음부터 전체) 또는 `"incremental"`(커서 이후만)."""

    environment: str
    """어느 LangFuse 프로젝트를 훑었는지."""

    added: int
    updated: int
    total: int
    """병합 후 **그 환경의** 저장 행 수."""

    stored_total: int
    """병합 후 저장된 전체 행 수(모든 환경 합계)."""

    fetched: int
    """이번에 LangFuse 에서 받은 행 수(중복 포함)."""

    pages: int
    completed: bool
    """마지막 페이지까지 갔으면 True. `max_pages` 로 끊겼으면 False."""


def sync(
    env: str,
    *,
    full: bool = False,
    page_size: int = PAGE_SIZE,
    max_pages: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> SyncResult:
    """한 환경의 LangFuse 로그를 받아 공용 저장소에 병합한다.

    커서가 없거나 `full` 이면 처음부터(=쌓인 로그 전체), 아니면 마지막으로 훑은 시각 이후만
    받는다. 어느 쪽이든 기존에 저장된 행은 지우지 않으며, **다른 환경의 행도 건드리지 않는다.**
    """
    environment = environments.validate(env)
    states = load_states()
    state = states.get(environment, {})
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
            env=environment,
        )
        batch = [row_of(trace, environment) for trace in getattr(response, "data", []) or []]
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

    environment_total = len(rows_of(rows, environment))
    # 이번에 훑은 구간의 끝까지만 커서를 옮긴다(아무것도 못 받았으면 이전 커서 유지).
    newest = watermark if watermark is not None else cursor
    states[environment] = {
        "backfilled": bool(state.get("backfilled")) or backfill,
        "last_timestamp": newest.isoformat() if newest is not None else None,
        "last_synced_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total": environment_total,
    }
    store.save_json(collection_state_file(), states)
    return SyncResult(
        mode="backfill" if backfill else "incremental",
        environment=environment,
        added=added,
        updated=updated,
        total=environment_total,
        stored_total=len(rows),
        fetched=fetched,
        pages=pages,
        completed=completed,
    )


def sync_all(
    envs: Sequence[str],
    *,
    full: bool = False,
    page_size: int = PAGE_SIZE,
    max_pages: int | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> list[SyncResult]:
    """여러 환경을 차례로 동기화한다. 결과는 넘긴 순서 그대로.

    한 환경이 실패해도 나머지는 계속 받도록 하지 않는다 — 예외는 그대로 올려서 화면이 어느
    환경에서 멈췄는지 그대로 보이게 한다.
    """
    results: list[SyncResult] = []
    for env in envs:
        def progress(pages: int, fetched: int, _env: str = env) -> None:
            if on_progress is not None:
                on_progress(_env, pages, fetched)

        results.append(
            sync(
                env,
                full=full,
                page_size=page_size,
                max_pages=max_pages,
                on_progress=progress,
            )
        )
    return results
