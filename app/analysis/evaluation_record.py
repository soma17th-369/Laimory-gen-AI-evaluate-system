"""채점 결과 레코드 — `data/evaluations/<taskId>.json` 의 계약.

Task 하나에 파일 하나다. 단계별로 따로 채점하므로 **한 단계를 채점하면 그 단계만 갱신**하고
나머지는 그대로 둔다. 종합 스코어는 저장할 때마다 남아 있는 단계 점수로 다시 계산한다.

```json
{
  "schemaVersion": 2,
  "taskId": "…", "traceId": "…", "env": "dev", "traceName": "generate-timeline",
  "composite": {"score": 84.6, "stageScores": {…}, "skipped": {…}},
  "stages": {
    "timeline": {
      "rubricRef": {"name": "judge-stage-timeline", "version": 1},
      "judgedAt": "…", "evidence": {"summary": {…}, "sections": ["실행 정보", …]},
      "scorecard": {"total": 78.0, "items": [...], "deductions": [...], "alerts": [...]}
    }
  }
}
```

근거 원문은 여기 담지 않는다. 정본은 `data/tasks/<taskId>/trace.json` 이고, 화면은 그것으로 근거를
다시 만들어 보여준다(같은 근거를 두 곳에 두면 어긋난다).

`schemaVersion` 이 없는 예전 레코드(7기준 0~10점 단일 카드)는 **읽기 전용**으로만 다룬다.

이 파일은 **최신 상태**만 들고 있다. 같은 단계를 여러 번 채점하면 실행마다 한 줄씩
`data/evaluations/history/<taskId>.jsonl` 에 쌓인다(→ [append_history][app.analysis.evaluation_record.append_history]).
채점자는 실행마다 점수가 달라지므로 편차를 보려면 이력이 필요하다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.analysis import rubric_store, stage_schema
from app.analysis.stage_schema import StageScore
from app.storage import store
from app.storage.paths import (
    evaluation_file,
    evaluation_history_dir,
    evaluation_history_file,
    evaluations_dir,
)

SCHEMA_VERSION = 2


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def is_legacy(record: dict[str, Any]) -> bool:
    """구버전(단일 scorecard) 레코드인지. 재채점·비교 대상에서 뺀다."""
    return int(record.get("schemaVersion") or 1) < SCHEMA_VERSION


def load(task_id: str) -> dict[str, Any] | None:
    data = store.load_json(evaluation_file(task_id))
    return data if isinstance(data, dict) else None


def load_all() -> list[tuple[Path, dict[str, Any]]]:
    """저장된 채점 결과 전부(최근 수정 순). 구버전 레코드도 그대로 읽는다."""
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in store.list_json(evaluations_dir()):
        data = store.load_json(path)
        if isinstance(data, dict):
            records.append((path, data))
    return sorted(records, key=lambda item: item[0].stat().st_mtime, reverse=True)


def _recompute_composite(record: dict[str, Any]) -> dict[str, Any]:
    """저장된 단계 점수로 종합 스코어를 다시 계산한다(채점된 대상의 단순 평균)."""
    totals = {
        key: (entry.get("scorecard") or {}).get("total")
        for key, entry in (record.get("stages") or {}).items()
    }
    evaluated = {key: value for key, value in totals.items() if isinstance(value, (int, float))}
    skipped = {
        key: ((entry.get("scorecard") or {}).get("skipReason") or "채점하지 않음")
        for key, entry in (record.get("stages") or {}).items()
        if not isinstance(totals.get(key), (int, float))
    }
    return {
        "score": round(sum(evaluated.values()) / len(evaluated), 1) if evaluated else None,
        "stageScores": evaluated,
        "skipped": skipped,
        "evaluatedCount": len(evaluated),
    }


def save_stages(
    *,
    task_id: str,
    trace_id: str | None,
    env: str,
    trace_name: str | None,
    date: str | None,
    results: dict[str, StageScore],
    rubric_refs: dict[str, dict[str, Any]],
    evidence_summaries: dict[str, dict[str, Any]],
    trace_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """단계 채점 결과를 레코드에 합쳐 저장한다. 준 단계만 갱신한다."""
    current = load(task_id)
    record: dict[str, Any]
    if current is None or is_legacy(current):
        # 구버전 레코드는 덮어쓰지 않고 새 구조로 시작한다(구버전 파일은 legacy 키에 남긴다).
        record = {"schemaVersion": SCHEMA_VERSION, "stages": {}}
        if current is not None:
            record["legacy"] = current
    else:
        record = dict(current)
        record.setdefault("stages", {})

    record.update(
        {
            "taskId": task_id,
            "traceId": trace_id,
            "env": env,
            "traceName": trace_name,
            "name": trace_name,  # 기존 화면이 쓰던 키를 유지한다
            "date": date,
            "updatedAt": now_iso(),
        }
    )
    for key, score in results.items():
        record["stages"][key] = {
            "rubricRef": rubric_refs.get(key),
            "judgedAt": now_iso(),
            "evidence": evidence_summaries.get(key) or {},
            "scorecard": score.to_dict(),
        }
    record["composite"] = _recompute_composite(record)
    store.save_json(evaluation_file(task_id), record)
    if results:
        append_history(
            task_id=task_id,
            trace_id=trace_id,
            env=env,
            trace_name=trace_name,
            date=date,
            results=results,
            rubric_refs=rubric_refs,
            trace_meta=trace_meta,
        )
    return record


def append_history(
    *,
    task_id: str,
    trace_id: str | None,
    env: str,
    trace_name: str | None,
    date: str | None,
    results: dict[str, StageScore],
    rubric_refs: dict[str, dict[str, Any]],
    trace_meta: dict[str, Any] | None = None,
) -> str:
    """채점 실행 하나를 이력에 덧붙인다(한 줄 = 단계 1회 채점).

    같은 단계를 여러 번 채점하면 최신 결과만 `evaluation_file` 에 남지만, 이력에는 실행마다 한 줄씩
    쌓인다. 채점자가 실행마다 다른 점수를 내므로 편차를 보려면 이 이력이 필요하다.
    """
    run_id = uuid4().hex[:12]
    stamp = now_iso()
    path = evaluation_history_file(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for key, score in results.items():
            file.write(
                json.dumps(
                    {
                        "runId": run_id,
                        "judgedAt": stamp,
                        "taskId": task_id,
                        "traceId": trace_id,
                        "env": env,
                        "traceName": trace_name,
                        "date": date,
                        "stageKey": key,
                        "label": score.label,
                        "total": score.total,
                        "rubricRef": rubric_refs.get(key),
                        "rubricEdited": rubric_store.is_edited(key),
                        # 점수와 무관한 기록: 대상 서버가 이 단계에 쓴 토큰·시간과 Task 전체 비용
                        "usage": score.extras.get("usage") or {},
                        "traceCost": (trace_meta or {}).get("cost"),
                        "traceLatency": (trace_meta or {}).get("latency"),
                        "traceTokens": (trace_meta or {}).get("tokens"),
                        "scorecard": score.to_dict(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return run_id


def load_history(task_id: str | None = None) -> list[dict[str, Any]]:
    """채점 실행 이력(최신순). `task_id` 를 주면 그 Task 만."""
    files = (
        [evaluation_history_file(task_id)]
        if task_id
        else sorted(evaluation_history_dir().glob("*.jsonl"))
    )
    runs: list[dict[str, Any]] = []
    for path in files:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 저장 중 끊긴 줄은 건너뛴다
    return sorted(runs, key=lambda run: run.get("judgedAt") or "", reverse=True)


def findings_text(record: dict[str, Any]) -> str:
    """단계별 감점 근거를 사람이 읽는 한 덩어리로 만든다.

    개선책·프롬프트 제안·테스트 데이터 생성이 같은 형식을 쓴다. **평가 대상(Agent)별로** 묶여
    있어 "어느 단계의 프롬프트를 고쳐야 하는지"가 그대로 드러난다.
    """
    lines = [f"## task {record.get('taskId')} (종합 {composite_score(record)}/100)"]
    for key, entry in (record.get("stages") or {}).items():
        card = entry.get("scorecard") or {}
        if card.get("total") is None:
            continue
        label = card.get("label") or key
        lines.append(f"### {label} {card['total']}/100 — {card.get('summary') or ''}")
        for alert in card.get("alerts") or []:
            lines.append(f"- [ALERT/{alert.get('kind')}] {alert.get('where')} — {alert.get('detail')}")
        for item in card.get("deductions") or []:
            refs = ", ".join(item.get("sourceRefs") or []) or "-"
            lines.append(
                f"- [{item.get('severity')}] ({item.get('itemKey')}) {item.get('description')} "
                f"· 입력 {refs} · 출력 {item.get('outputPath')}"
            )
    return "\n".join(lines)


def stage_score(record: dict[str, Any], stage_key: str) -> dict[str, Any] | None:
    """저장된 단계 채점 결과 하나."""
    entry = (record.get("stages") or {}).get(stage_key)
    return entry if isinstance(entry, dict) else None


def composite_score(record: dict[str, Any]) -> float | None:
    """종합 스코어. 구버전 레코드는 0~10 점수를 100점으로 환산해 비교 가능하게 만든다."""
    if is_legacy(record):
        legacy = ((record.get("scorecard") or {}).get("overall") or {}).get("score")
        return round(float(legacy) * 10, 1) if isinstance(legacy, (int, float)) else None
    return (record.get("composite") or {}).get("score")


def to_stage_scores(record: dict[str, Any]) -> list[StageScore]:
    """저장된 레코드 → 계산용 StageScore 목록(집계·비교에 쓴다)."""
    scores: list[StageScore] = []
    for key, entry in (record.get("stages") or {}).items():
        card = entry.get("scorecard") or {}
        scores.append(
            StageScore(
                stage_key=key,
                label=card.get("label") or key,
                total=card.get("total"),
                items=tuple(
                    stage_schema.ScoredItem(
                        key=item.get("key"),
                        label=item.get("label"),
                        score=item.get("score") or 0,
                        points=item.get("points") or 0,
                        applied_points=item.get("appliedPoints") or 0.0,
                        applied=bool(item.get("applied")),
                        reason=item.get("reason") or "",
                    )
                    for item in card.get("items") or []
                ),
                deductions=tuple(card.get("deductions") or []),
                alerts=tuple(card.get("alerts") or []),
                summary=card.get("summary") or "",
                skip_reason=card.get("skipReason"),
                extras={
                    "usage": card.get("usage") or {},
                    "scoringPolicy": card.get("scoringPolicy"),
                    "checks": card.get("checks") or {},
                },
            )
        )
    return scores
