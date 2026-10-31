"""단계별 채점 근거 슬라이서 — trace.json 에서 "그 단계가 본 것과 만든 것"만 잘라낸다.

원칙 넷:

1. **자르되 요약하지 않는다.** 남기기로 한 부분은 원문 그대로 넣는다. 요약하면 채점자가 근거를
   대조할 수 없다.
2. **그 단계의 입력만 넣는다.** 대상 서버는 Event Agent 5종에 수집 원본 전체를 똑같이 넘긴다.
   그대로 채점하면 "자기 source 만 보고 만들었는지"를 잴 수 없으므로 해당 source 배열만 남긴다.
3. **화면과 프롬프트가 같은 것을 본다.** [sections][app.analysis.evidence.StageEvidence.sections]
   하나로 프롬프트를 만들고 화면도 그린다. 채점 근거와 화면이 어긋날 수 없다.
4. **없으면 N/A.** 입력이 0건이거나 단계가 실행되지 않았으면 채점하지 않고 이유를 남긴다.
   0점이 아니다(문서 규칙: 평가할 입력이 없는 기준은 감점하지 않는다).

단계 식별은 관측치 이름이 아니라 `step.metadata`(agent·iteration·tool·phase)를 쓴다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.analysis import stages
from app.analysis.stages import StageSpec
from app.tasks.trace_builder import resolve

_EVENT_AGENTS = {
    "event-location": ("location", ("stays", "movements")),
    "event-calendar": ("calendar", ("calendars",)),
    "event-notification": ("notification", ("notifications",)),
    "event-photo": ("photo", ("photos",)),
}
"""stageKey → (metadata.agent 값, 그 단계가 실제로 담당하는 source 배열)."""

_PROMPT_SECTION = re.compile(r"^\[(?P<name>[A-Za-z][A-Za-z0-9 _-]*)\][ \t]*$", re.MULTILINE)


@dataclass(frozen=True)
class EvidenceSection:
    """근거 한 덩어리. 프롬프트의 `[제목]` 블록이자 화면의 소제목 하나."""

    title: str
    note: str
    payload: Any

    @property
    def is_empty(self) -> bool:
        return self.payload in (None, [], {}, "")


@dataclass(frozen=True)
class StageEvidence:
    """단계 하나의 채점 근거. 채점할 수 없으면 `applicable=False` 와 이유만 들고 있다."""

    stage: StageSpec
    applicable: bool
    skip_reason: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    sections: tuple[EvidenceSection, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    """대상 서버가 이 단계에 쓴 토큰·시간. 채점 점수와는 무관하고 기록용이다."""

    @property
    def key(self) -> str:
        return self.stage.key


def _steps(trace_json: dict) -> list[dict]:
    return list((trace_json.get("process") or {}).get("steps") or [])


def _generations(trace_json: dict) -> list[dict]:
    return list((trace_json.get("process") or {}).get("generations") or [])


def _step_by_agent(trace_json: dict, agent: str) -> dict | None:
    for step in _steps(trace_json):
        if (step.get("metadata") or {}).get("agent") == agent:
            return step
    return None


def _step_by_name(trace_json: dict, name: str) -> dict | None:
    return next((step for step in _steps(trace_json) if step.get("name") == name), None)


def _generation_by_name(trace_json: dict, name: str) -> dict | None:
    return next((gen for gen in _generations(trace_json) if gen.get("name") == name), None)


def _generations_of(trace_json: dict, step: dict | None) -> list[dict]:
    if step is None:
        return []
    ids = set(step.get("generationRefs") or [])
    return [gen for gen in _generations(trace_json) if gen.get("id") in ids]


def _messages(trace_json: dict, ref: str | None) -> Any:
    """GENERATION 의 프롬프트·출력. messages 리스트면 그대로, 그 외 형태도 원문 그대로 둔다."""
    return resolve(trace_json, ref)


def _message_text(payload: Any, role: str) -> str | None:
    """messages 에서 특정 role 의 content 를 꺼낸다."""
    if not isinstance(payload, list):
        return None
    for message in payload:
        if isinstance(message, dict) and message.get("role") == role:
            return str(message.get("content", ""))
    return None


def prompt_section(text: str | None, name: str) -> str | None:
    """대상 서버 프롬프트의 `[블록]` 하나를 꺼낸다. 없으면 None.

    User Memory 원문은 수집 원본(`request.userMemory`)에 없고 프롬프트 안에만 있다. 블록 이름이
    바뀌면 못 찾는데, 그때는 해당 근거만 비고 채점은 계속된다(항목이 N/A 로 떨어진다).
    """
    if not text:
        return None
    matches = list(_PROMPT_SECTION.finditer(text))
    for index, match in enumerate(matches):
        if match.group("name").strip() != name:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        return body or None
    return None


def parse_json_array(value: Any) -> list[dict] | None:
    """events 블록 선두의 JSON 배열. 뒤의 자연어 실행 지시는 원문에 남기고 배열만 읽는다."""
    if isinstance(value, str):
        text = value.strip()
        try:
            value, end = json.JSONDecoder().raw_decode(text)
        except (ValueError, TypeError):
            return None
        if text[end:].lstrip().startswith(("[", "{", ",")):
            return None  # 여러 JSON 값을 임의로 하나로 축약하지 않는다.
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        return None
    return value


def stage_usage(step: dict | None) -> dict[str, Any]:
    """대상 서버가 그 단계에 쓴 토큰·시간. 점수에는 넣지 않고 이력에만 남긴다."""
    output = (step or {}).get("output") or {}
    tokens = output.get("tokenUsage") or {}
    return {
        "durationMs": output.get("durationMs"),
        "generationCount": tokens.get("generationCount"),
        "inputTokens": tokens.get("inputTokens"),
        "outputTokens": tokens.get("outputTokens"),
        "totalTokens": tokens.get("totalTokens"),
    }


def _header(trace_json: dict, step: dict | None) -> dict:
    """모든 단계에 공통으로 붙는 실행 정보. 실패 여부를 여기서 알린다."""
    task = trace_json.get("task") or {}
    source = trace_json.get("source") or {}
    header = {
        "taskId": task.get("taskId"),
        "date": source.get("date"),
        "timezone": source.get("timezone"),
        "window": task.get("window"),
        "traceStatus": (trace_json.get("operation") or {}).get("status"),
    }
    if step is not None:
        header["stageLevel"] = step.get("level")
        header["stageStatusMessage"] = step.get("statusMessage")
    return header


def _prompt_sections(trace_json: dict, generation: dict | None, label: str) -> list[EvidenceSection]:
    """그 단계가 실제로 받은 지시. 무엇을 지시받고 그렇게 했는지 판단할 때 쓴다."""
    if generation is None:
        return []
    return [
        EvidenceSection(
            title=f"{label} 프롬프트",
            note="대상 서버가 이 단계에 실제로 준 지시(system·user). 채점 기준이 아니라 참고 근거다.",
            payload=_messages(trace_json, generation.get("inputRef")),
        )
    ]


def _event_agent_evidence(trace_json: dict, spec: StageSpec) -> StageEvidence:
    agent, source_keys = _EVENT_AGENTS[spec.key]
    step = _step_by_agent(trace_json, agent)
    source = trace_json.get("source") or {}
    counts = {key: len(source.get(key) or []) for key in source_keys}
    total = sum(counts.values())

    if step is None:
        return StageEvidence(spec, False, f"{spec.label} 관측치가 트레이스에 없습니다.", counts)
    if total == 0:
        return StageEvidence(spec, False, f"입력이 0건입니다({', '.join(source_keys)}).", counts)

    result = (step.get("output") or {}).get("result") or {}
    sections = [
        EvidenceSection("실행 정보", "이 단계가 언제·어떤 상태로 실행됐는지.", _header(trace_json, step)),
        EvidenceSection(
            "입력 source",
            f"이 단계가 담당하는 원본만 넣는다({', '.join(source_keys)}). 다른 source 는 이 단계의 근거가 아니다.",
            {key: source.get(key) or [] for key in source_keys},
        ),
    ]

    if spec.key == "event-photo":
        describe = _generation_by_name(trace_json, "describe-photo-images")
        sections.append(
            EvidenceSection(
                "Vision 결과",
                "사진 묘사의 유일한 근거. 여기 없는 사람·행동·장소를 쓰면 vision 결과 밖 주장이다.",
                _messages(trace_json, describe.get("outputRef")) if describe else None,
            )
        )

    sections.append(
        EvidenceSection(
            "출력 candidate·fragment·warning",
            "이 단계가 만든 것 전부.",
            {
                "candidates": result.get("candidates") or [],
                "fragments": result.get("fragments") or [],
                "warnings": result.get("warnings") or [],
            },
        )
    )
    sections.extend(_prompt_sections(trace_json, next(iter(_generations_of(trace_json, step)), None), spec.label))

    summary = counts | {
        "candidates": len(result.get("candidates") or []),
        "fragments": len(result.get("fragments") or []),
        "warnings": len(result.get("warnings") or []),
    }
    return StageEvidence(spec, True, None, summary, tuple(sections), stage_usage(step))


def _timeline_evidence(trace_json: dict, spec: StageSpec) -> StageEvidence:
    step = _step_by_agent(trace_json, "timeline")
    if step is None:
        return StageEvidence(spec, False, "Timeline Agent 관측치가 트레이스에 없습니다.")
    draft = resolve(trace_json, step.get("timelineRef"))
    if not isinstance(draft, dict):
        return StageEvidence(spec, False, "Timeline Agent 가 draft 를 만들지 못했습니다(실행 실패).")

    merge = _step_by_name(trace_json, "merge-event-results")
    merged = (merge or {}).get("output", {}).get("mergedResult") or {}
    generation = next(iter(_generations_of(trace_json, step)), None)
    user_prompt = _message_text(_messages(trace_json, (generation or {}).get("inputRef")), "user")

    sections = (
        EvidenceSection("실행 정보", "이 단계가 언제·어떤 상태로 실행됐는지.", _header(trace_json, step)),
        EvidenceSection(
            "입력 candidate·fragment",
            "Event Agent 들이 넘긴 근거. Timeline 은 candidate 를 우선 쓰고 fragment 로 보충해야 한다.",
            {
                "candidates": merged.get("candidates") or [],
                "fragments": merged.get("fragments") or [],
                "warnings": merged.get("warnings") or [],
            },
        ),
        EvidenceSection(
            "입력 수집 원본",
            "candidate 의 rawId 를 대조할 원본. 없는 사실을 만들었는지 여기서 확인한다.",
            trace_json.get("source") or {},
        ),
        EvidenceSection(
            "입력 User Memory",
            "프롬프트에 실제로 들어간 User Memory. 수집 원본에는 해시만 남아 여기서만 확인된다.",
            prompt_section(user_prompt, "user memory"),
        ),
        EvidenceSection("출력 draft timeline", "이 단계가 만든 타임라인 초안 전부(events·warnings).", draft),
        *_prompt_sections(trace_json, generation, spec.label),
    )
    summary = {
        "candidates": len(merged.get("candidates") or []),
        "fragments": len(merged.get("fragments") or []),
        "events": len(draft.get("events") or []),
        "warnings": len(draft.get("warnings") or []),
    }
    return StageEvidence(spec, True, None, summary, sections, stage_usage(step))


def _repair_iterations(trace_json: dict) -> list[dict]:
    """회차별 계획·도구 실행·결과. 회차 순서대로."""
    by_iteration: dict[Any, dict] = {}
    for step in _steps(trace_json):
        meta = step.get("metadata") or {}
        iteration = meta.get("iteration")
        if iteration is None:
            continue
        entry = by_iteration.setdefault(iteration, {"iteration": iteration, "toolCalls": []})
        name = step.get("name") or ""
        if name == "analyze-repair-iteration":
            entry["plan"] = (step.get("output") or {}).get("plan")
        elif name == "execute-repair-plan":
            entry["results"] = (step.get("output") or {}).get("results")
        elif name == "confirm-repair-iteration":
            entry["timelineRef"] = step.get("timelineRef")
    # execute-<tool> 은 iteration metadata 가 없고 execute-repair-plan 의 자식이다.
    plans = {
        step.get("id"): (step.get("metadata") or {}).get("iteration")
        for step in _steps(trace_json)
        if step.get("name") == "execute-repair-plan"
    }
    for step in _steps(trace_json):
        iteration = plans.get(step.get("parentId"))
        if iteration is None:
            continue
        by_iteration.setdefault(iteration, {"iteration": iteration, "toolCalls": []})["toolCalls"].append(
            {
                "tool": (step.get("metadata") or {}).get("tool"),
                "call": (step.get("input") or {}).get("call"),
                "level": step.get("level"),
                "result": (step.get("output") or {}).get("result"),
                "ok": (step.get("output") or {}).get("ok"),
            }
        )
    return [by_iteration[key] for key in sorted(by_iteration, key=lambda value: (value is None, value))]


def _repair_evidence(trace_json: dict, spec: StageSpec) -> StageEvidence:
    step = _step_by_agent(trace_json, "repair")
    if step is None:
        return StageEvidence(spec, False, "Repair Agent 관측치가 트레이스에 없습니다.")
    iterations = _repair_iterations(trace_json)
    if not any(entry.get("plan") for entry in iterations):
        return StageEvidence(spec, False, "Repair 반복이 한 번도 실행되지 않았습니다.")

    timeline_step = _step_by_agent(trace_json, "timeline")
    before = resolve(trace_json, (timeline_step or {}).get("timelineRef"))
    after = resolve(trace_json, step.get("timelineRef"))
    event_results = {
        (candidate.get("metadata") or {}).get("agent"): (candidate.get("output") or {}).get("result")
        for candidate in _steps(trace_json)
        if (candidate.get("metadata") or {}).get("sourceStage") == "event"
    }
    # 회차 종료본은 참조만 두면 화면에서 못 보므로, 회차별로 event 요약만 펼친다(전문 중복 방지).
    for entry in iterations:
        timeline = resolve(trace_json, entry.pop("timelineRef", None))
        entry["resultEvents"] = [
            {
                "clientEventId": event.get("clientEventId"),
                "eventType": event.get("eventType"),
                "title": event.get("title"),
                "startTime": event.get("startTime"),
                "endTime": event.get("endTime"),
            }
            for event in (timeline or {}).get("events") or []
        ]

    sections = (
        EvidenceSection("실행 정보", "이 단계가 언제·어떤 상태로 실행됐는지.", _header(trace_json, step)),
        EvidenceSection("수정 전 draft", "Repair 가 받은 타임라인. 문제 발견의 대상이다.", before),
        EvidenceSection(
            "근거 원본",
            "draft 주장을 검증할 수집 원본과 Agent 결과. lookup_source 없이 고칠 수 있었는지 여기서 본다.",
            {"source": trace_json.get("source") or {}, "eventResults": event_results},
        ),
        EvidenceSection(
            "회차별 계획과 도구 실행",
            "회차마다 issues·toolCalls·done·summary 와 실제 도구 호출·결과. 회차 종료본은 event 요약만 담았다.",
            iterations,
        ),
        EvidenceSection("수정 후 timeline", "Repair 가 끝내고 넘긴 타임라인 전부.", after),
        *_prompt_sections(
            trace_json, _generation_by_name(trace_json, "analyze-timeline-repair"), "Repair analyze"
        ),
    )
    summary = {
        "iterations": len(iterations),
        "issues": sum(len(((entry.get("plan") or {}).get("issues")) or []) for entry in iterations),
        "toolCalls": sum(len(entry.get("toolCalls") or []) for entry in iterations),
        "eventsBefore": len((before or {}).get("events") or []),
        "eventsAfter": len((after or {}).get("events") or []),
    }
    return StageEvidence(spec, True, None, summary, sections, stage_usage(step))


def _question_evidence(trace_json: dict, spec: StageSpec) -> StageEvidence:
    step = _step_by_agent(trace_json, "question")
    if step is None:
        return StageEvidence(spec, False, "Question Agent 관측치가 트레이스에 없습니다.")
    timeline = resolve(trace_json, step.get("timelineRef")) or {}
    events = timeline.get("events") or []
    generation = next(iter(_generations_of(trace_json, step)), None)
    user_prompt = _message_text(_messages(trace_json, (generation or {}).get("inputRef")), "user")
    input_events = prompt_section(user_prompt, "events")
    parsed_inputs = parse_json_array(input_events)
    if not events and not (isinstance(parsed_inputs, list) and parsed_inputs):
        return StageEvidence(spec, False, "질문을 붙일 event 가 0건이거나 입력 근거를 읽을 수 없습니다.")
    # 질문은 events[].question 에 embedded 된다. 예전 로그는 timeline.questions 배열이었다.
    embedded = [
        {"clientEventId": event.get("clientEventId"), "question": event.get("question")}
        for event in events
    ]
    questions = embedded if any(item["question"] for item in embedded) else (timeline.get("questions") or embedded)

    sections = (
        EvidenceSection("실행 정보", "이 단계가 언제·어떤 상태로 실행됐는지.", _header(trace_json, step)),
        EvidenceSection(
            "입력 event",
            "질문이 전제할 수 있는 사실의 전부. timeOfDay 는 프롬프트에만 있어 원문 그대로 넣는다.",
            input_events or events,
        ),
        EvidenceSection(
            "입력 User Memory",
            "질문 표현에만 쓸 수 있는 보조 정보. 여기 있는 사실을 event 의 사실로 쓰면 안 된다.",
            prompt_section(user_prompt, "user memory"),
        ),
        EvidenceSection("출력 질문", "event 마다 붙은 질문 전부.", questions),
        *_prompt_sections(trace_json, generation, spec.label),
    )
    summary = {
        "events": len(parsed_inputs) if parsed_inputs is not None else len(events),
        "questions": sum(1 for item in questions or [] if (item or {}).get("question")),
    }
    return StageEvidence(spec, True, None, summary, sections, stage_usage(step))


def _user_memory_evidence(trace_json: dict, spec: StageSpec) -> StageEvidence:
    generation = _generation_by_name(trace_json, "update-user-memory-profile")
    if generation is None:
        return StageEvidence(spec, False, "User Memory 갱신 GENERATION 이 트레이스에 없습니다.")
    prompt = _messages(trace_json, generation.get("inputRef"))
    output = _messages(trace_json, generation.get("outputRef"))
    if output is None:
        return StageEvidence(spec, False, "User Memory Agent 출력이 로그에 없습니다.")
    user_prompt = _message_text(prompt, "user")

    sections = (
        EvidenceSection("실행 정보", "이 단계가 언제·어떤 상태로 실행됐는지.", _header(trace_json, None)),
        EvidenceSection(
            "기존 프로필",
            "갱신 전 User Memory. 유지·병합·교체 판단의 기준이다.",
            prompt_section(user_prompt, "existing user memory"),
        ),
        EvidenceSection(
            "입력 기록",
            "이번에 반영해야 할 timeline·memo 근거.",
            prompt_section(user_prompt, "dailyTimelines"),
        ),
        EvidenceSection("출력 프로필", "Agent 가 새로 쓴 User Memory 전문.", output),
        *_prompt_sections(trace_json, generation, spec.label),
    )
    summary = {"hasExisting": bool(prompt_section(user_prompt, "existing user memory"))}
    return StageEvidence(
        spec, True, None, summary, sections, stage_usage(_step_by_name(trace_json, "update-user-memory"))
    )


_BUILDERS = {
    "timeline": _timeline_evidence,
    "repair": _repair_evidence,
    "question": _question_evidence,
    "user-memory": _user_memory_evidence,
}


def build(trace_json: dict, stage_key: str) -> StageEvidence:
    """단계 하나의 채점 근거. 채점할 수 없으면 `applicable=False` 로 돌아온다."""
    spec = stages.get(stage_key)
    trace_name = (trace_json.get("task") or {}).get("traceName")
    if trace_name and trace_name != spec.trace_name:
        return StageEvidence(
            spec, False, f"이 트레이스(`{trace_name}`)가 아니라 `{spec.trace_name}` 에서 채점하는 단계입니다."
        )
    builder = _BUILDERS.get(stage_key)
    if builder is not None:
        return builder(trace_json, spec)
    return _event_agent_evidence(trace_json, spec)


def build_all(trace_json: dict) -> list[StageEvidence]:
    """그 트레이스에서 다룰 수 있는 단계 전부(채점 불가 사유 포함)."""
    trace_name = (trace_json.get("task") or {}).get("traceName")
    specs = stages.for_trace(trace_name) or stages.STAGES
    return [build(trace_json, spec.key) for spec in specs]


def _as_text(payload: Any) -> str:
    if payload is None:
        return "(없음)"
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(payload)


def build_user_prompt(evidence: StageEvidence) -> str:
    """근거를 채점 입력 메시지로 조립한다. 화면에 보이는 근거와 같은 내용·같은 순서다."""
    blocks = [
        f"평가 대상: {evidence.stage.label}",
        "아래 근거는 이 단계의 입력과 출력이다. 다른 단계의 결과는 채점 대상이 아니다.",
    ]
    for section in evidence.sections:
        blocks.append(f"[{section.title}] — {section.note}\n{_as_text(section.payload)}")
    blocks.append(
        "위 근거만으로 채점 기준의 **모든 항목**에 점수와 이유를 매겨라. 근거에 없는 사실을 지어내지 "
        "말고, 평가할 입력이 없는 항목은 `applied=false` 로 표시하라."
    )
    return "\n\n".join(blocks)
