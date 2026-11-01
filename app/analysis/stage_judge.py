"""단계별 LLM-as-a-Judge 실행.

단계 하나마다 (1) 그 단계의 근거만 자르고 (2) 메트릭 문서 원문을 채점 기준으로 주고 (3) 항목별
세부 기준별 통과 건수·이유를 구조화 출력으로 받는다. 항목 점수는 calibration.score,
총점은 [stage_schema.tally][app.analysis.stage_schema.tally]가 계산한다.

채점 기준의 정본은 **현재 채점 항목**이다(메트릭 문서 기본값 + 설정 화면에서 고친 편집본,
→ [app.analysis.stages.get][]). 프롬프트는 채점할 때마다 그 항목으로 다시 만들어지므로, 항목을
고치면 다음 채점부터 바로 반영된다. 레지스트리(`judge-stage-<stageKey>`)에는 **실제로 쓴 본문을
기록**해 두어, 나중에 어떤 기준으로 매긴 점수인지 되짚을 수 있게 한다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.analysis import calibration, evidence, stage_schema, stages
from app.analysis.evidence import StageEvidence
from app.analysis.providers import get_llm_provider
from app.analysis.stage_schema import StageScore
from app.analysis.stages import StageSpec
from app.prompts import registry

RUBRIC_PREFIX = "judge-stage-"

_JUDGE_ROLE = """\
당신은 Laimory 생성형 AI 파이프라인의 **{label}** 결과를 채점하는 엄정한 채점자다.

- 아래 채점 기준 문서에 있는 **모든 항목**의 세부 기준을 판정하고, 기준마다 이유를 남긴다. 만점이어도
  무엇을 확인해 문제가 없었는지 적는다.
- 오직 주어진 근거(이 단계의 입력·출력)만으로 판단한다. 근거에 없는 사실을 지어내지 않는다.
- **감점(0점)과 미평가(N/A)는 다르다.** 그 항목을 평가할 입력이 근거에 하나도 없으면 0점을 주지 말고
  해당 기준을 `total=0, passed=0` 으로 둔다. 입력은 있는데 필수 결과가 없거나 틀리면 실패다.
  세부 판정에 따라 항목 점수와 applied 및 총점은 코드가 계산한다.
- 감점은 `deductions` 에 입력 rawId·출력 위치(field 경로)와 함께 적는다.
- 입력에서 확인되지 않는 사실, 필수 반영 source 누락, 민감정보 검출은 점수와 별개로 `alerts` 에 적는다.
- 모든 텍스트는 한국어로 쓰고, 지정된 JSON 스키마로만 답한다.

아래는 채점 기준 문서 원문이다. 요약본이 아니라 정본이므로 여기 적힌 확인 기준을 그대로 적용한다.

"""


def rubric_name(stage_key: str) -> str:
    """단계별 채점 기준의 레지스트리 이름."""
    return f"{RUBRIC_PREFIX}{stage_key}"


def default_rubric(spec: StageSpec) -> str:
    """채점자 지시 + 공통 규칙 + 채점 항목(키·배점·확인 기준) + 점수 작성 형식."""
    return _JUDGE_ROLE.format(label=spec.label) + stages.rubric_text(spec) + "\n\n" + calibration.prompt(spec)


def system_prompt(stage_key: str) -> str:
    """지금 채점에 쓸 기준 본문. 현재 채점 항목으로 매번 새로 만든다."""
    return default_rubric(stages.get(stage_key))


def register_rubric(stage_key: str, content: str, *, note: str = "", source: str = "judge") -> dict:
    """채점에 쓴 기준을 버전으로 확정한다(같은 본문이면 기존 버전 재사용)."""
    return registry.get_or_create(rubric_name(stage_key), content, note=note, source=source)


def score_evidence(
    stage_evidence: StageEvidence,
    *,
    system_prompt_text: str | None = None,
) -> StageScore:
    """근거 하나를 채점한다. 근거가 없으면 LLM 을 부르지 않고 N/A 로 돌려준다."""
    spec = stage_evidence.stage
    if not stage_evidence.applicable:
        return stage_schema.skipped(
            spec, stage_evidence.skip_reason or "채점할 근거가 없습니다.", usage=stage_evidence.usage
        )
    from app.analysis.deterministic_checks import confirmed_checks

    confirmed = confirmed_checks(stage_evidence)
    user_prompt = evidence.build_user_prompt(stage_evidence)
    if confirmed:
        user_prompt += "\n\n[확정 판정 — 코드 계산]\n" + evidence._as_text(confirmed)
    user_prompt += "\n\n점수·applied 대신 지정된 모든 기준 ID의 total·passed·failedRefs·reason을 반환하라."
    card = get_llm_provider().evaluate(
        system_prompt=system_prompt_text or system_prompt(spec.key),
        user_prompt=user_prompt,
        result_model=calibration.result_model(spec),
    )
    for key, values in confirmed.items():
        for check_id, value in values.items():
            setattr(getattr(card.items, key), check_id, calibration.CheckAssessment.model_validate(value))
    return calibration.score(spec, card, usage=stage_evidence.usage)


def score_stage(
    trace_json: dict,
    stage_key: str,
    *,
    system_prompt_text: str | None = None,
) -> StageScore:
    """trace.json 에서 단계 하나를 채점한다."""
    return score_evidence(
        evidence.build(trace_json, stage_key), system_prompt_text=system_prompt_text
    )


def score_stages(
    trace_json: dict,
    stage_keys: list[str],
    *,
    workers: int = 3,
    prompts: dict[str, str] | None = None,
    on_done: Callable[[str, StageScore | None, Exception | None], None] | None = None,
) -> dict[str, StageScore]:
    """여러 단계를 병렬로 채점한다. 한 단계가 실패해도 나머지는 계속한다.

    `on_done` 은 단계가 **끝난 순서대로** (stageKey, 결과, 예외) 로 불린다. 호출부는 여기서 바로
    저장한다. 오래 걸리는 단계를 기다리느라 끝난 단계의 저장이 밀리면, 그 사이 프로세스가 죽을 때
    끝난 결과까지 잃는다.
    """
    results: dict[str, StageScore] = {}
    evidences = {key: evidence.build(trace_json, key) for key in stage_keys}
    # 근거가 없는 단계는 LLM 호출 없이 먼저 정리한다.
    pending = []
    for key, item in evidences.items():
        if not item.applicable:
            results[key] = stage_schema.skipped(
                item.stage, item.skip_reason or "채점할 근거가 없습니다.", usage=item.usage
            )
            if on_done is not None:
                on_done(key, results[key], None)
        else:
            pending.append(key)

    if not pending:
        return results

    def run(key: str) -> StageScore:
        return score_evidence(
            evidences[key], system_prompt_text=(prompts or {}).get(key)
        )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(run, key): key for key in pending}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
                error: Exception | None = None
            except Exception as exc:  # noqa: BLE001 — 한 단계 실패가 전체를 막지 않는다
                error = exc
            if on_done is not None:
                on_done(key, results.get(key), error)
    return {key: results[key] for key in stage_keys if key in results}


def composite(results: dict[str, StageScore] | list[StageScore]) -> dict[str, Any]:
    """종합 스코어(채점된 대상의 단순 평균)."""
    values = list(results.values()) if isinstance(results, dict) else list(results)
    return stage_schema.composite(values)
