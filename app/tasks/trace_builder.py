"""LangFuse 트레이스 → `trace.json` 정규화 (안내 명세 준수).

명세 핵심: source→process→result→operation 4역할 분리 + **중복 금지**.
- 최종 타임라인 정본 = `result.timeline`(main-agent). 다른 step 은 저장하지 않는다.
- 프롬프트 정본 = `process.generations[].input`. step 은 `generationRefs` 로만 가리킨다.
- 수집 원본 정본 = `source.*`(trace.input.request). step 은 `inputRefs` 로 가리킨다.
- 운영 메타 = `operation`(trace.output). 타임라인과 완전 분리.

주: `inputRefs` 의 의미적 참조 추론과 "의미 있는 step" 선별은 실물 관측치 이름이 명세 예시와
정확히 일치하지 않으므로 **휴리스틱**이다(store/finalize→result.timeline, 하위 GENERATION 이름으로
source 추정). 나머지는 비우고 사람이 process.steps 순서로 흐름을 읽게 한다. — 필요시 규칙 보강.
"""

from __future__ import annotations

from typing import Any

from app.analysis.judge import find_final_timeline

_GENERATION = "GENERATION"

# 하위 GENERATION 이름 키워드 → source 참조 (inputRefs 휴리스틱)
_SOURCE_BY_KEYWORD = {
    "location": ["source.stays", "source.movements"],
    "notification": ["source.notifications"],
    "photo": ["source.photos"],
    "calendar": ["source.calendars"],
    "health": ["source.healths"],
}


def _obs_type(observation: Any) -> Any:
    t = getattr(observation, "type", None)
    return getattr(t, "value", t)


def _usage(observation: Any) -> Any:
    details = getattr(observation, "usage_details", None)
    if isinstance(details, dict) and details:
        return details
    usage = getattr(observation, "usage", None)
    if usage is not None:
        return {
            "input": getattr(usage, "input", None),
            "output": getattr(usage, "output", None),
            "total": getattr(usage, "total", None),
        }
    return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _step_output(output: Any) -> Any:
    """단계의 의미 있는 새 출력만. 최종 타임라인 중복(`timeline` 키)은 제거한다."""
    if not isinstance(output, dict):
        return output or None
    cleaned = {k: v for k, v in output.items() if k != "timeline"}
    return cleaned or None


def _input_refs(name: str, child_generation_names: list[str]) -> list[str]:
    """의미적 입력 참조(휴리스틱). 데이터를 복제하지 않고 source/result 를 가리킨다."""
    lname = (name or "").lower()
    refs: list[str] = []
    if "store" in lname or "finalize" in lname:
        refs.append("result.timeline")
    for gen_name in child_generation_names:
        for keyword, source_refs in _SOURCE_BY_KEYWORD.items():
            if keyword in (gen_name or "").lower():
                refs.extend(source_refs)
    return sorted(set(refs))


def build_trace_json(trace_detail: Any) -> dict:
    """LangFuse 트레이스 상세 → 명세 구조의 trace.json dict."""
    observations = list(getattr(trace_detail, "observations", []) or [])
    trace_input = getattr(trace_detail, "input", None) or {}
    request = trace_input.get("request", {}) if isinstance(trace_input, dict) else {}
    trace_output = getattr(trace_detail, "output", None) or {}

    # task
    task = {
        "taskId": trace_input.get("taskId") if isinstance(trace_input, dict) else None,
        "dailyRecordId": trace_input.get("dailyRecordId") if isinstance(trace_input, dict) else None,
        "window": trace_input.get("window") if isinstance(trace_input, dict) else None,
    }

    # source ← trace.input.request (정본)
    source = {
        "date": request.get("date"),
        "timezone": request.get("timezone"),
        "userMemory": request.get("userMemory"),
        "stays": request.get("stays") or [],
        "movements": request.get("movements") or [],
        "calendars": request.get("calendars") or [],
        "notifications": request.get("notifications") or [],
        "photos": request.get("photos") or [],
        "healths": request.get("healths") or [],
    }

    # generations ← GENERATION 관측치 (프롬프트 정본)
    generations = []
    for obs in observations:
        if _obs_type(obs) != _GENERATION:
            continue
        generations.append(
            {
                "id": getattr(obs, "id", None),
                "stepId": getattr(obs, "parent_observation_id", None),
                "name": getattr(obs, "name", None),
                "model": getattr(obs, "model", None),
                "input": getattr(obs, "input", None),
                "usage": _usage(obs),
            }
        )
    generations_by_step: dict[Any, list[dict]] = {}
    for gen in generations:
        generations_by_step.setdefault(gen["stepId"], []).append(gen)

    # steps ← GENERATION 제외, start_time 순
    step_obs = [o for o in observations if _obs_type(o) != _GENERATION]
    step_obs.sort(key=lambda o: (getattr(o, "start_time", None) is None, getattr(o, "start_time", None)))
    steps = []
    for order, obs in enumerate(step_obs, start=1):
        obs_id = getattr(obs, "id", None)
        child_gens = generations_by_step.get(obs_id, [])
        child_gen_names = [g["name"] for g in child_gens]
        steps.append(
            {
                "id": obs_id,
                "name": getattr(obs, "name", None),
                "type": _obs_type(obs),
                "parentId": getattr(obs, "parent_observation_id", None),
                "order": order,
                "startedAt": _iso(getattr(obs, "start_time", None)),
                "inputRefs": _input_refs(getattr(obs, "name", None), child_gen_names),
                "output": _step_output(getattr(obs, "output", None)),
                "generationRefs": [g["id"] for g in child_gens],
            }
        )

    # result ← main-agent.output.timeline (최종 타임라인 유일 정본)
    result = {"timeline": find_final_timeline(trace_detail)}

    # operation ← trace.output (운영 메타, 타임라인과 분리)
    operation = dict(trace_output) if isinstance(trace_output, dict) else {}

    return {
        "task": task,
        "source": source,
        "process": {"steps": steps, "generations": generations},
        "result": result,
        "operation": operation,
        "langfuse": {"observationCount": len(observations)},
    }
