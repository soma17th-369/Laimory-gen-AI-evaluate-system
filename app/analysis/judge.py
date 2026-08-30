"""LLM judge (M2).

선택한 트레이스의 근거를 조립해 설정된 Judge Provider로 채점한다. 기본 provider는 로컬에서
ChatGPT 계정으로 인증된 Codex CLI이고 OpenAI API 직접 호출은 deprecated 선택지로 남긴다.
"""

from __future__ import annotations

from typing import Any

from app.analysis.providers import get_judge_provider
from app.analysis.rubric import SYSTEM_PROMPT, build_user_prompt
from app.analysis.schema import CRITERION_KEYS, METRIC_KEYS, TraceScorecard


# 최종 타임라인을 담는 관측치 이름 우선순위. main agent 그래프의 산출 위치(AGENT.md 참고).
_TIMELINE_OBS_PRIORITY = ("main-agent", "question-agent", "store-timeline")


def _observation_timeline(observation: Any) -> Any:
    """관측치 output 에서 events 배열을 가진 timeline dict 를 꺼낸다. 없으면 None."""
    out = getattr(observation, "output", None)
    if isinstance(out, dict):
        timeline = out.get("timeline")
        if isinstance(timeline, dict) and isinstance(timeline.get("events"), list):
            return timeline
    return None


def find_final_timeline(trace_detail: Any) -> Any:
    """트레이스에서 채점 대상인 최종 타임라인(events 포함)을 찾는다.

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


_SOURCE_KEYS = (
    "date",
    "timezone",
    "userMemory",
    "stays",
    "movements",
    "calendars",
    "notifications",
    "photos",
    "healths",
)


def _canonical_input(trace_detail: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """중복된 trace.input에서 task 식별자와 source 정본만 분리한다."""
    raw = getattr(trace_detail, "input", None)
    if not isinstance(raw, dict):
        return {"rawInputType": type(raw).__name__}, {"raw": raw}

    request = raw.get("request") if isinstance(raw.get("request"), dict) else {}
    task = {
        "taskId": raw.get("taskId") or request.get("taskId"),
        "dailyRecordId": raw.get("dailyRecordId") or request.get("dailyRecordId"),
        "window": raw.get("window") or request.get("window"),
    }
    source = {
        key: request.get(key) if key in {"date", "timezone", "userMemory"} else request.get(key) or []
        for key in _SOURCE_KEYS
    }
    return task, source


def assemble_evidence(trace_detail: Any) -> dict:
    """트레이스 상세 → judge 근거 dict(이름·입력·최종 타임라인·관측치 요약).

    출력 근거는 **관측치의 최종 타임라인**이다. 못 찾으면 ``trace.output`` 으로 폴백하되,
    그 사실을 근거에 표시해 judge 가 불완전 근거임을 알게 한다.
    """
    observations = list(getattr(trace_detail, "observations", []) or [])
    obs_brief = [
        {
            "type": getattr(getattr(o, "type", None), "value", getattr(o, "type", None)),
            "name": getattr(o, "name", None),
        }
        for o in observations
    ]
    task, source = _canonical_input(trace_detail)
    timeline = find_final_timeline(trace_detail)
    if timeline is not None:
        output = timeline
        output_source = "관측치 최종 타임라인(events)"
    else:
        output = getattr(trace_detail, "output", None)
        output_source = "trace.output 폴백 — 최종 타임라인을 못 찾음(불완전 근거)"
    return {
        "name": getattr(trace_detail, "name", None),
        "task": task,
        "source": source,
        "output": output,
        "output_source": output_source,
        "observations": obs_brief,
    }


def _clamp_scores(card: TraceScorecard) -> TraceScorecard:
    """모델의 점수·Metric을 v4 범위와 null 규칙에 맞춘다."""
    def clamp(value: int) -> int:
        return max(0, min(10, value))

    for key in CRITERION_KEYS:
        item = getattr(card.scores, key)
        item.score = clamp(item.score)
    card.overall.score = clamp(card.overall.score)

    for key in METRIC_KEYS:
        metric = getattr(card.metrics, key)
        if metric.denominator is None or metric.denominator <= 0:
            metric.value = None
            metric.numerator = None
            metric.denominator = None
            if "계산 대상" not in metric.reason and "분모" not in metric.reason:
                metric.reason = f"{metric.reason.rstrip()} 계산 대상 또는 유효한 분모가 없어 null이다."
            continue
        if metric.numerator is not None:
            metric.numerator = max(0.0, metric.numerator)
        metric.denominator = max(0.0, metric.denominator)
        if metric.value is None:
            continue
        if key == "meanTemporalIoU":
            metric.value = round(max(0.0, min(1.0, metric.value)), 3)
        elif key == "meanBoundaryErrorMinutes":
            metric.value = round(max(0.0, metric.value), 1)
        else:
            metric.value = round(max(0.0, min(100.0, metric.value)), 1)
    return card


def score_trace(trace_detail: Any, *, system_prompt: str | None = None) -> TraceScorecard:
    """트레이스 하나를 채점해 TraceScorecard 를 돌려준다.

    `system_prompt` 를 주면 그 채점 기준으로 채점한다(UI 편집본). 없으면 기본 rubric.
    점수 항목(7기준+전반)과 v3 Metric 20개는 스키마가 고정하므로 기준을 바꿔도 구조는 유지된다.
    """
    card = get_judge_provider().evaluate(
        system_prompt=system_prompt or SYSTEM_PROMPT,
        user_prompt=build_user_prompt(assemble_evidence(trace_detail)),
        result_model=TraceScorecard,
    )
    return _clamp_scores(card)
