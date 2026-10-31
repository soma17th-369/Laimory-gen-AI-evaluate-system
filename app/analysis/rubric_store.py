"""채점 항목 편집본 저장소 — 화면에서 고친 항목이 곧 채점 기준이 된다.

기본값은 메트릭 문서다(→ [app.analysis.metric_doc][]). 문서를 그대로 쓰는 동안에는 저장 파일이
없고, 설정 화면에서 항목을 고치는 순간 `data/rubrics/<stageKey>.json` 이 생겨 **그 단계의 채점
기준을 대체**한다. 채점 프롬프트는 항상 이 결과로 만들어지므로, 고친 내용이 바로 다음 채점에 나간다.

```json
{
  "stageKey": "timeline",
  "updatedAt": "2026-09-07T…",
  "items": [{"key": "day_flow", "label": "하루 흐름", "points": 15, "criteria": "- …"}]
}
```

지키는 규칙 셋(저장 때 검사한다):

- 배점 합계는 100점이어야 한다(문서 규칙).
- 항목 키는 결과 스키마의 field 이름이라 파이썬 식별자여야 하고 중복될 수 없다.
- 확인 기준이 빈 항목은 둘 수 없다. 기준 없는 배점은 채점자가 무엇을 볼지 알 수 없다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.storage import store
from app.storage.paths import rubric_dir, rubric_file

TOTAL_POINTS = 100


class RubricEditError(ValueError):
    """편집본이 규칙을 어겼을 때. 화면이 그대로 사용자에게 보여준다."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load(stage_key: str) -> list[dict[str, Any]] | None:
    """저장된 편집본 항목 목록. 없으면 None(= 문서 기본값을 쓴다)."""
    data = store.load_json(rubric_file(stage_key))
    if not isinstance(data, dict):
        return None
    items = data.get("items")
    return items if isinstance(items, list) and items else None


def updated_at(stage_key: str) -> str | None:
    data = store.load_json(rubric_file(stage_key))
    return (data or {}).get("updatedAt") if isinstance(data, dict) else None


def is_edited(stage_key: str) -> bool:
    return load(stage_key) is not None


def edited_stages() -> set[str]:
    """편집본이 있는 단계 키. 화면이 '문서 기본값'과 구분해 표시한다."""
    return {path.stem for path in store.list_json(rubric_dir())}


def validate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """편집본을 저장 가능한 형태로 검사·정리한다. 어긋나면 RebricEditError."""
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in items:
        key = str(row.get("key") or "").strip()
        label = str(row.get("label") or "").strip()
        criteria = str(row.get("criteria") or "").strip()
        try:
            points = int(row.get("points"))
        except (TypeError, ValueError) as exc:
            raise RubricEditError(f"`{key or label}` 의 배점이 숫자가 아닙니다.") from exc

        if not key:
            raise RubricEditError("항목 키가 비어 있는 줄이 있습니다.")
        if not key.isidentifier():
            raise RubricEditError(f"항목 키 `{key}` 는 영문·숫자·밑줄만 쓸 수 있습니다(채점 결과의 field 이름).")
        if key in seen:
            raise RubricEditError(f"항목 키 `{key}` 가 중복됩니다.")
        if points < 0:
            raise RubricEditError(f"`{label or key}` 의 배점이 음수입니다.")
        if not criteria:
            raise RubricEditError(f"`{label or key}` 의 확인 기준이 비어 있습니다.")
        seen.add(key)
        cleaned.append({"key": key, "label": label or key, "points": points, "criteria": criteria})

    if not cleaned:
        raise RubricEditError("항목이 하나도 없습니다.")
    total = sum(row["points"] for row in cleaned)
    if total != TOTAL_POINTS:
        raise RubricEditError(f"배점 합계가 {total}점입니다. {TOTAL_POINTS}점에 맞춰야 합니다.")
    return cleaned


def save(stage_key: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """편집본을 저장한다. 저장 즉시 그 단계의 채점 기준이 바뀐다."""
    cleaned = validate(items)
    store.save_json(
        rubric_file(stage_key),
        {"stageKey": stage_key, "updatedAt": _now_iso(), "items": cleaned},
    )
    return cleaned


def reset(stage_key: str) -> None:
    """편집본을 지우고 문서 기본값으로 되돌린다."""
    path = rubric_file(stage_key)
    if path.exists():
        path.unlink()
