"""개선책 레코드 — 저장·상태 관리의 **정본**.

`data/improvements/<slug>.json` 한 파일이 개선책 하나다. 생성 당시 정보(`plan`·`instruction`·
`taskIds`)에 더해 **반영 상태**를 함께 들고 있는다.

```json
{
  "slug": "verify",
  "taskIds": ["..."],
  "instruction": "...",
  "plan": "## 개선책 …",
  "createdAt": "2026-08-20T16:40:00+09:00",
  "status": "applied",
  "appliedAt": "2026-08-20T16:40:00+09:00",
  "note": "generate-timeline 프롬프트에 시간 근거 규칙 추가"
}
```

상태 필드가 없던 예전 파일도 그대로 읽는다([normalize][app.improve.records.normalize] 가
`draft`·파일 mtime 으로 채운다). 개선 history 는 `status == "applied"` 이고 `appliedAt` 이 있는
레코드만 비교 대상으로 본다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.storage import store
from app.storage.paths import improvement_file, improvements_dir

STATUS_DRAFT = "draft"
STATUS_APPLIED = "applied"
STATUS_DROPPED = "dropped"

STATUS_LABELS: dict[str, str] = {
    STATUS_DRAFT: "미반영",
    STATUS_APPLIED: "반영됨",
    STATUS_DROPPED: "보류",
}
"""상태 키 → 화면 라벨. 화면은 이 표만 쓰고 문자열을 따로 만들지 않는다."""


def _file_time(path: Path) -> str:
    """파일 mtime 을 로컬 타임존 ISO 문자열로(생성 시각이 없던 예전 레코드용)."""
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return stamp.astimezone().isoformat(timespec="seconds")


def now_iso() -> str:
    """지금 시각(로컬 타임존 ISO). 반영 시기 기본값."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize(record: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """저장된 dict 를 현재 계약으로 맞춘다. 없는 상태 필드는 기본값으로 채운다."""
    data = dict(record)
    data.setdefault("slug", path.stem if path is not None else "unnamed")
    data.setdefault("taskIds", [])
    data.setdefault("plan", "")
    status = data.get("status")
    data["status"] = status if status in STATUS_LABELS else STATUS_DRAFT
    data["appliedAt"] = data.get("appliedAt") or None
    data["note"] = data.get("note") or ""
    if not data.get("createdAt"):
        data["createdAt"] = _file_time(path) if path is not None else now_iso()
    # 반영 상태가 아니면 반영 시기를 들고 있지 않는다(비교 대상 판정이 흐려진다).
    if data["status"] != STATUS_APPLIED:
        data["appliedAt"] = None
    return data


def load(slug: str) -> dict[str, Any] | None:
    """slug 하나를 읽어 정규화. 없으면 None."""
    path = improvement_file(slug)
    data = store.load_json(path)
    return normalize(data, path) if isinstance(data, dict) else None


def load_all() -> list[dict[str, Any]]:
    """저장된 개선책 전체(최신 생성 순)."""
    records = []
    for path in store.list_json(improvements_dir()):
        data = store.load_json(path)
        if isinstance(data, dict):
            records.append(normalize(data, path))
    return sorted(records, key=lambda r: r.get("createdAt") or "", reverse=True)


def applied(records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """반영 시기가 확정된 개선책만(개선 history 의 비교 대상). 반영 시기 오름차순."""
    source = load_all() if records is None else records
    done = [r for r in source if r.get("status") == STATUS_APPLIED and r.get("appliedAt")]
    return sorted(done, key=lambda r: r["appliedAt"])


def save_status(slug: str, *, status: str, applied_at: str | None, note: str) -> dict[str, Any]:
    """상태·반영 시기·메모만 갱신해 저장한다. 개선책 본문(plan)은 건드리지 않는다."""
    if status not in STATUS_LABELS:
        raise ValueError(f"알 수 없는 상태: {status}")
    path = improvement_file(slug)
    current = store.load_json(path)
    if not isinstance(current, dict):
        raise FileNotFoundError(f"개선책을 찾을 수 없습니다: {slug}")
    record = normalize(current, path)
    record["status"] = status
    record["appliedAt"] = (applied_at or now_iso()) if status == STATUS_APPLIED else None
    record["note"] = note or ""
    store.save_json(path, record)
    return record
