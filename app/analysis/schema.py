"""채점 결과 계약 (M2).

OpenAI structured output(`chat.completions.parse`)의 `response_format` 으로 쓰는 Pydantic
모델. 점수 범위(0~10)는 스키마에 minimum/maximum 을 넣지 않고(strict 모드 호환) 프롬프트로
지시한 뒤 코드에서 clamp 한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["HIGH", "MED", "LOW"]

# 채점 기준 키 → 화면 표시 라벨. 결정론 코드가 의존하는 유일한 정본.
CRITERION_LABELS: dict[str, str] = {
    "grounding": "근거 충실성/환각",
    "temporal": "시간 정합성",
    "place": "장소 정합성",
    "coverage": "완결성",
    "writing": "문장 품질(노출)",
    "question": "회고 질문",
    "overall": "전반",
}

# scores 안의 기준 순서(overall 제외).
CRITERION_KEYS: tuple[str, ...] = ("grounding", "temporal", "place", "coverage", "writing", "question")


class ScoreItem(BaseModel):
    score: int = Field(description="0~10 정수 (0=심각한 위반, 10=문제 없음)")
    reason: str = Field(description="점수 근거 한 줄(한국어)")


class RubricScores(BaseModel):
    grounding: ScoreItem = Field(description="근거 충실성/환각: 출력이 입력 근거에 기반하는가, 지어낸 것은 없는가")
    temporal: ScoreItem = Field(description="시간 정합성: 시각·순서가 window·수면·근거와 모순 없는가")
    place: ScoreItem = Field(description="장소 정합성: 장소/주소가 근거에 있고 잘못 붙지 않았는가")
    coverage: ScoreItem = Field(description="완결성: 주요 활동·일정 누락 없이 하루가 설명되는가")
    writing: ScoreItem = Field(description="문장 품질: 1인칭 해요체 과거형, 추정표현·원시수치 배제, 길이 적정")
    question: ScoreItem = Field(description="회고 질문: 모든 event 에 해요체 의문문·40자 내외 질문이 붙었는가")


class Finding(BaseModel):
    criterion: str = Field(description="관련 기준 키(grounding/temporal/place/coverage/writing/question/overall)")
    severity: Severity = Field(description="심각도")
    description: str = Field(description="문제 내용(한국어)")


class TraceScorecard(BaseModel):
    scores: RubricScores
    overall: ScoreItem = Field(description="전반: 하루 기록으로서의 종합 품질(0~10)")
    findings: list[Finding] = Field(description="발견한 문제점 목록(없으면 빈 리스트)")
    summary: str = Field(description="종합 평가 1~2문장(한국어)")
