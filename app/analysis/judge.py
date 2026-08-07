"""LLM judge (M2).

선택한 트레이스의 근거를 조립해 OpenAI structured output 으로 채점한다. 모델은 설정
(`OPENAI_JUDGE_MODEL`, 기본 gpt-4o)에서 받아 언제든 교체 가능. 키는 SecretStr 로만 다루고
값을 로그·화면에 남기지 않는다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from openai import OpenAI

from app.analysis.rubric import SYSTEM_PROMPT, _as_text, build_user_prompt
from app.analysis.schema import CRITERION_KEYS, TraceScorecard
from app.config import get_settings


class OpenAINotConfigured(RuntimeError):
    """OpenAI 키가 없어 채점할 수 없을 때."""


@lru_cache
def get_openai_client() -> OpenAI:
    settings = get_settings()
    if not settings.has_openai_credentials():
        raise OpenAINotConfigured(
            "OPENAI_API_KEY 가 없습니다. .env 에 설정하세요(.env.example 참고)."
        )
    # get_secret_value() 는 SDK 생성자에만 전달하고 저장·로깅하지 않는다.
    return OpenAI(api_key=settings.openai_api_key.get_secret_value())


def assemble_evidence(trace_detail: Any) -> dict:
    """트레이스 상세 → judge 근거 dict(이름·입력·출력·관측치 요약). 본문은 잘라서 담는다."""
    observations = list(getattr(trace_detail, "observations", []) or [])
    obs_brief = [
        {
            "type": getattr(getattr(o, "type", None), "value", getattr(o, "type", None)),
            "name": getattr(o, "name", None),
        }
        for o in observations
    ]
    return {
        "name": getattr(trace_detail, "name", None),
        "input": _as_text(getattr(trace_detail, "input", None)),
        "output": _as_text(getattr(trace_detail, "output", None)),
        "observations": obs_brief,
    }


def _clamp_scores(card: TraceScorecard) -> TraceScorecard:
    """혹시 모델이 0~10 밖을 내면 잘라 맞춘다(스키마엔 범위 제약을 두지 않으므로)."""
    def clamp(value: int) -> int:
        return max(0, min(10, value))

    for key in CRITERION_KEYS:
        item = getattr(card.scores, key)
        item.score = clamp(item.score)
    card.overall.score = clamp(card.overall.score)
    return card


def score_trace(trace_detail: Any) -> TraceScorecard:
    """트레이스 하나를 채점해 TraceScorecard 를 돌려준다."""
    client = get_openai_client()
    model = get_settings().openai_judge_model
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(assemble_evidence(trace_detail))},
    ]

    def _parse(**extra):
        return client.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=TraceScorecard,
            **extra,
        )

    try:
        completion = _parse(temperature=0)
    except Exception as exc:  # noqa: BLE001
        # 일부 모델(o-series)은 temperature 조정을 막는다 → 빼고 재시도
        if "temperature" in str(exc).lower():
            completion = _parse()
        else:
            raise

    card = completion.choices[0].message.parsed
    if card is None:
        raise RuntimeError("모델이 구조화 결과를 반환하지 않았습니다(거부 또는 형식 실패).")
    return _clamp_scores(card)
