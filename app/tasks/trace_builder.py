"""LangFuse 트레이스 → `trace.json` 정규화 (schemaVersion 2).

명세 핵심은 그대로다: source→process→result→operation 4역할 분리 + **중복 금지**. v2 에서
바뀐 것은 **단계별 채점에 필요한 근거를 버리지 않는다**는 점이다.

- v1 은 step 의 `timeline` 키를 전부 지우고 `step.input`·`generation.output` 을 저장하지 않았다.
  그 결과 저장된 trace.json 만으로는 "Timeline Agent 가 무엇을 받아 무엇을 만들었는지"를 알 수
  없었다. LangFuse 보존기간이 30일이라 지나면 복구도 안 된다.
- v2 는 그 셋을 모두 담되, **같은 내용을 두 번 담지 않는다.** 반복되는 큰 값(프롬프트·타임라인
  스냅샷)은 `process.blobs` 에 한 번만 넣고 나머지는 참조(`…Ref`)로 가리킨다.

정본 규칙:

- 수집 원본 정본 = `source.*`(trace.input.request). step 의 `request` 는 저장하지 않고
  `inputRefs` 로 가리킨다.
- 최종 타임라인 정본 = `result.timeline`. 단계별 중간 타임라인은 `step.timelineRef` 로 blob 을
  가리키고, 같은 내용이면 같은 ref 를 공유한다.
- 프롬프트·LLM 출력 정본 = `process.generations[].inputRef`·`outputRef`(blob).
- 단계 식별자는 `step.metadata`(agent·sourceStage·iteration·tool·phase)와 `level` 이다.
  이름 문자열 대신 이 값을 쓴다(툴 실행은 이름에 괄호가 붙어 나오는 사례가 있다).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = 2

# 최종 타임라인을 담는 관측치 이름 우선순위. main agent 그래프의 산출 위치(AGENT.md 참고).
_TIMELINE_OBS_PRIORITY = ("main-agent", "question-agent", "store-timeline")

_GENERATION = "GENERATION"

# step.output 에서 그 시점 타임라인을 **보존할** 단계. 나머지는 통과 중복이라 버린다.
_TIMELINE_STEPS = frozenset(
    {
        "main-agent",
        "timeline-agent",
        "repair-agent",
        "question-agent",
        "confirm-timeline-draft",
        "confirm-repair-iteration",
    }
)

# step.input·output 에서 다른 정본과 겹치는 키. 저장하지 않고 참조로 대신한다.
_DROPPED_INPUT_KEYS = frozenset(
    {
        "request",  # → source.*
        "timeline",  # → 직전 단계의 timelineRef
        "mergedResult",  # → merge-event-results.output.mergedResult
        "eventResults",  # → event-agent-*.output.result
        "system",  # → 하위 GENERATION 의 프롬프트
        "prompt",
    }
)
_DROPPED_OUTPUT_KEYS = frozenset({"timeline", "snapshot", "request"})

# 하위 GENERATION 이름 키워드 → source 참조 (inputRefs 휴리스틱)
_SOURCE_BY_KEYWORD = {
    "location": ["source.stays", "source.movements"],
    "notification": ["source.notifications"],
    "photo": ["source.photos"],
    "calendar": ["source.calendars"],
    "health": ["source.healths"],
}

_META_KEYS = ("agent", "sourceStage", "iteration", "maxIterations", "tool", "phase", "stage", "imageCount")
"""단계 판정에 쓰는 metadata 키만 남긴다. resourceAttributes 같은 SDK 잡음은 버린다."""


class _BlobPool:
    """같은 내용을 한 번만 저장하고 참조를 돌려주는 pool."""

    def __init__(self) -> None:
        self.blobs: dict[str, Any] = {}
        self._by_digest: dict[str, str] = {}

    def put(self, value: Any) -> str | None:
        """값을 넣고 참조 키를 돌려준다. `None` 은 저장하지 않는다."""
        if value is None:
            return None
        try:
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            encoded = str(value)
        digest = hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:12]
        ref = self._by_digest.get(digest)
        if ref is None:
            ref = f"b{len(self.blobs) + 1}"
            self._by_digest[digest] = ref
            self.blobs[ref] = value
        return ref


def resolve(trace_json: dict, ref: str | None) -> Any:
    """`…Ref` 값을 실제 내용으로 돌려준다. 없으면 None."""
    if not ref:
        return None
    return ((trace_json.get("process") or {}).get("blobs") or {}).get(ref)


def _observation_timeline(observation: Any) -> Any:
    """관측치 output 에서 events 배열을 가진 timeline dict 를 꺼낸다. 없으면 None."""
    out = getattr(observation, "output", None)
    if isinstance(out, dict):
        timeline = out.get("timeline")
        if isinstance(timeline, dict) and isinstance(timeline.get("events"), list):
            return timeline
    return None


def find_final_timeline(trace_detail: Any) -> Any:
    """트레이스에서 최종 타임라인(events 포함)을 찾는다.

    실제 산출물은 ``trace.output``(운영 메타)이 아니라 관측치 output 의 ``timeline`` 에 있다.
    main-agent(오케스트레이터 최종 결과)를 우선하고, 없으면 다른 관측치를 훑는다.
    """
    observations = list(getattr(trace_detail, "observations", []) or [])
    by_name = {getattr(o, "name", None): o for o in observations}
    for name in _TIMELINE_OBS_PRIORITY:
        observation = by_name.get(name)
        if observation is not None:
            timeline = _observation_timeline(observation)
            if timeline is not None:
                return timeline
    for observation in observations:
        timeline = _observation_timeline(observation)
        if timeline is not None:
            return timeline
    return None


def _obs_type(observation: Any) -> Any:
    t = getattr(observation, "type", None)
    return getattr(t, "value", t)


def _level(observation: Any) -> Any:
    level = getattr(observation, "level", None)
    return getattr(level, "value", level)


def _metadata(observation: Any) -> dict:
    raw = getattr(observation, "metadata", None)
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in _META_KEYS if key in raw}


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


def _without(payload: Any, dropped: frozenset[str]) -> Any:
    """dict 에서 중복 정본 키만 뺀다. 남는 게 없으면 None."""
    if not isinstance(payload, dict):
        return payload or None
    cleaned = {key: value for key, value in payload.items() if key not in dropped}
    return cleaned or None


def _step_timeline(observation: Any) -> Any:
    """그 단계가 확정한 타임라인. 보존 대상 단계가 아니면 None."""
    if getattr(observation, "name", None) not in _TIMELINE_STEPS:
        return None
    output = getattr(observation, "output", None)
    if isinstance(output, dict):
        timeline = output.get("timeline")
        if isinstance(timeline, dict):
            return timeline
    return None


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
    pool = _BlobPool()

    # task ← 트레이스 식별 정보. 어느 흐름(timeline·user-memory)인지도 여기서 정한다.
    task = {
        "taskId": trace_input.get("taskId") if isinstance(trace_input, dict) else None,
        "dailyRecordId": trace_input.get("dailyRecordId") if isinstance(trace_input, dict) else None,
        "window": trace_input.get("window") if isinstance(trace_input, dict) else None,
        "traceId": getattr(trace_detail, "id", None),
        "traceName": getattr(trace_detail, "name", None),
        "sessionId": getattr(trace_detail, "session_id", None),
        "tags": list(getattr(trace_detail, "tags", None) or []),
        "timestamp": _iso(getattr(trace_detail, "timestamp", None)),
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

    # generations ← GENERATION 관측치. 프롬프트·출력은 blob 으로 한 번만 저장한다.
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
                "level": _level(obs),
                "metadata": _metadata(obs),
                "inputRef": pool.put(getattr(obs, "input", None)),
                "outputRef": pool.put(getattr(obs, "output", None)),
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
                "endedAt": _iso(getattr(obs, "end_time", None)),
                "level": _level(obs),
                "statusMessage": getattr(obs, "status_message", None),
                "metadata": _metadata(obs),
                "inputRefs": _input_refs(getattr(obs, "name", None), child_gen_names),
                "input": _without(getattr(obs, "input", None), _DROPPED_INPUT_KEYS),
                "output": _without(getattr(obs, "output", None), _DROPPED_OUTPUT_KEYS),
                "timelineRef": pool.put(_step_timeline(obs)),
                "generationRefs": [g["id"] for g in child_gens],
            }
        )

    # result ← main-agent.output.timeline (최종 타임라인 유일 정본)
    result = {"timeline": find_final_timeline(trace_detail)}

    # operation ← trace.output (운영 메타, 타임라인과 분리)
    operation = _without(trace_output, frozenset({"timeline"})) or {}

    return {
        "schemaVersion": SCHEMA_VERSION,
        "task": task,
        "source": source,
        "process": {"steps": steps, "generations": generations, "blobs": pool.blobs},
        "result": result,
        "operation": operation,
        "langfuse": {"observationCount": len(observations)},
    }
