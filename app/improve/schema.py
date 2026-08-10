"""프롬프트 개선 제안 계약 (M4a). OpenAI structured output 으로 받는다."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PromptSuggestion(BaseModel):
    target_step: str = Field(description="고칠 프롬프트의 단계 이름(generation name). 예: generate-timeline")
    related_criteria: list[str] = Field(
        description="관련 채점 기준 키(grounding/temporal/place/coverage/writing/question)"
    )
    problem: str = Field(description="현재 프롬프트가 유발하거나 방치하는 문제(한국어)")
    suggestion: str = Field(description="구체적 수정 방향 — 무엇을 추가·수정·삭제할지(한국어)")


class PromptReview(BaseModel):
    suggestions: list[PromptSuggestion] = Field(description="단계별 개선 제안(없으면 빈 리스트)")
    summary: str = Field(description="개선 방향 종합 1~2문장(한국어)")
