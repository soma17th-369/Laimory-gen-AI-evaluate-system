"""프롬프트 개선 제안 (M4a).

트레이스의 GENERATION 관측치에서 **실제 프롬프트**(messages)를 뽑아, 채점 결과의 문제점과
대조해 단계별 수정안을 낸다. judge 와 같은 OpenAI 클라이언트·모델을 쓴다.
"""

from __future__ import annotations

from typing import Any

from app.analysis.judge import get_openai_client
from app.analysis.schema import CRITERION_LABELS, TraceScorecard
from app.config import get_settings
from app.improve.schema import PromptReview

_GENERATION = "GENERATION"


def _obs_type(observation: Any) -> Any:
    t = getattr(observation, "type", None)
    return getattr(t, "value", t)


def collect_generation_prompts(trace_detail: Any, *, per_msg_limit: int = 3000) -> list[dict]:
    """GENERATION 관측치에서 프롬프트(messages)를 뽑는다. 같은 단계명은 처음 것만(중복 축소)."""
    prompts: list[dict] = []
    seen: set[str] = set()
    for observation in getattr(trace_detail, "observations", []) or []:
        if _obs_type(observation) != _GENERATION:
            continue
        name = getattr(observation, "name", None)
        if name in seen:
            continue
        seen.add(name)
        messages = []
        raw = getattr(observation, "input", None)
        if isinstance(raw, list):
            for msg in raw:
                if isinstance(msg, dict):
                    content = str(msg.get("content", ""))
                    if len(content) > per_msg_limit:
                        content = content[:per_msg_limit] + f"…(생략: 총 {len(content)}자)"
                    messages.append({"role": msg.get("role"), "content": content})
        prompts.append({"name": name, "model": getattr(observation, "model", None), "messages": messages})
    return prompts


_SYSTEM_PROMPT = """\
당신은 LLM 파이프라인의 프롬프트를 개선하는 프롬프트 엔지니어다.
입력으로 (1) 파이프라인 각 단계의 실제 프롬프트와 (2) 그 실행 결과의 채점 문제점을 받는다.
각 문제점을 줄이려면 **어느 단계의 프롬프트를(target_step)** 어떻게 고쳐야 하는지 구체적으로
제안하라.

규칙:
- 오직 주어진 실제 프롬프트 내용에 근거해 제안한다. 없는 지시문을 있다고 가정하지 않는다.
- 제안은 실행 가능해야 한다("이런 문장을 추가/수정/삭제" 수준). 추상적 훈수 금지.
- target_step 은 반드시 주어진 단계 이름 중 하나를 쓴다.
- 모든 텍스트는 한국어. 지정된 JSON 스키마로만 답한다.
"""


def _findings_text(scorecard: TraceScorecard) -> str:
    lines = [f"- 종합 {scorecard.overall.score}/10: {scorecard.summary}"]
    for finding in scorecard.findings:
        label = CRITERION_LABELS.get(finding.criterion, finding.criterion)
        lines.append(f"- [{finding.severity}] ({label}) {finding.description}")
    return "\n".join(lines)


def _prompts_text(prompts: list[dict]) -> str:
    blocks = []
    for p in prompts:
        msgs = "\n".join(f"  <{m.get('role')}>\n  {m.get('content')}" for m in p["messages"])
        blocks.append(f"### 단계: {p['name']} (model={p['model']})\n{msgs}")
    return "\n\n".join(blocks) or "(프롬프트 없음)"


def suggest_prompt_improvements(trace_detail: Any, scorecard: TraceScorecard) -> PromptReview:
    """트레이스의 프롬프트 + 채점 문제점 → 단계별 개선 제안."""
    prompts = collect_generation_prompts(trace_detail)
    user = (
        "[채점 문제점]\n"
        f"{_findings_text(scorecard)}\n\n"
        "[파이프라인 단계별 실제 프롬프트]\n"
        f"{_prompts_text(prompts)}\n\n"
        "위 문제점을 줄이기 위한 단계별 프롬프트 수정안을 제안하라."
    )
    client = get_openai_client()
    model = get_settings().openai_judge_model

    def _parse(**extra):
        return client.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user}],
            response_format=PromptReview,
            **extra,
        )

    try:
        completion = _parse(temperature=0)
    except Exception as exc:  # noqa: BLE001
        if "temperature" in str(exc).lower():
            completion = _parse()
        else:
            raise

    review = completion.choices[0].message.parsed
    if review is None:
        raise RuntimeError("모델이 구조화 결과를 반환하지 않았습니다.")
    return review
