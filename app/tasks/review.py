"""Task 채점 흐름 — 화면과 MCP 서버가 같은 코드를 쓰게 하는 공용 계층.

채점 대상을 고르는 규칙과 "채점하고 저장하기"를 여기 모은다. 화면(→ [app.ui.task_review][])은
진행 표시만 덧붙이고, `streamlit` 없이도 이 모듈만으로 같은 결과가 저장된다.

수집 목록에는 대상 서버의 **테스트 실행**(taskId 가 `task-test` 고정, 비용 0, 관측치 1~7개)이
실제 실행보다 훨씬 많다. 채점 대상은 이름이 맞고 taskId 가 UUID 형식인 실제 실행뿐이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from app.analysis import evaluation_record, evidence, stage_judge, stages
from app.analysis.stage_schema import StageScore
from app.storage import store
from app.storage.paths import task_trace_file

SCORABLE_NAMES = frozenset({stages.TIMELINE_TRACE, stages.USER_MEMORY_TRACE})
"""채점 대상 트레이스 이름. 나머지 이름은 대상 서버 테스트가 남긴 조각이다."""

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-9a-f][0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def is_scorable(row: dict[str, Any]) -> bool:
    """실제 실행인지. 이름이 맞고 taskId 가 UUID 형식이어야 한다(`task-test` 등 제외)."""
    if row.get("name") not in SCORABLE_NAMES:
        return False
    task_id = str(row.get("taskId") or "")
    return bool(_UUID.match(task_id))


def domain_task_id(trace_detail: Any, trace_id: str) -> str:
    raw = getattr(trace_detail, "input", None)
    if isinstance(raw, dict):
        tid = raw.get("taskId") or (raw.get("request") or {}).get("taskId")
        if tid:
            return str(tid)
    return trace_id


def scored_index() -> dict[str, dict[str, Any]]:
    """taskId → 저장된 채점 결과. 목록에 채점 여부를 붙이는 데 쓴다."""
    return {
        str(record.get("taskId") or path.stem): record
        for path, record in evaluation_record.load_all()
    }


@dataclass(frozen=True)
class JudgeOutcome:
    """채점 한 번의 결과. 실패한 단계는 `failures` 로만 남고 저장되지 않는다."""

    record: dict[str, Any]
    results: dict[str, StageScore]
    failures: dict[str, Exception]


def judge(
    *,
    trace_json: dict,
    stage_keys: list[str],
    task_id: str,
    trace_id: str,
    env: str,
    workers: int = 3,
    trace_meta: dict[str, Any] | None = None,
    on_stage: Callable[[str, Exception | None], None] | None = None,
) -> JudgeOutcome:
    """선택한 단계를 채점하고 결과를 저장한다. 한 단계가 실패해도 나머지는 남긴다.

    `on_stage` 는 단계가 끝날 때마다 (stageKey, 예외) 로 불린다. 화면 진행 표시에 쓴다.
    """
    # 채점 기준은 현재 채점 항목으로 매번 새로 만든다(설정 화면에서 고친 내용이 바로 나간다).
    prompts = {key: stage_judge.system_prompt(key) for key in stage_keys}
    evidences = {key: evidence.build(trace_json, key) for key in stage_keys}
    failures: dict[str, Exception] = {}

    def on_done(stage_key: str, _score: StageScore | None, error: Exception | None) -> None:
        if error is not None:
            failures[stage_key] = error
        if on_stage is not None:
            on_stage(stage_key, error)

    results = stage_judge.score_stages(
        trace_json, stage_keys, workers=workers, prompts=prompts, on_done=on_done
    )

    rubric_refs = {}
    for key in results:
        version = stage_judge.register_rubric(key, prompts[key], note="단계 채점")
        rubric_refs[key] = {"name": version["name"], "version": version["version"]}
    summaries = {
        key: {
            "summary": evidences[key].summary,
            "sections": [section.title for section in evidences[key].sections],
        }
        for key in results
    }
    record = evaluation_record.save_stages(
        task_id=task_id,
        trace_id=trace_id,
        env=env,
        trace_name=(trace_json.get("task") or {}).get("traceName"),
        date=(trace_json.get("source") or {}).get("date"),
        results=results,
        rubric_refs=rubric_refs,
        evidence_summaries=summaries,
        trace_meta=trace_meta,
    )
    store.save_json(task_trace_file(task_id), trace_json)
    return JudgeOutcome(record, results, failures)
