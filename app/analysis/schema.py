"""채점 결과 계약 (M2).

OpenAI structured output(`chat.completions.parse`)의 `response_format` 으로 쓰는 Pydantic
모델. 점수 범위(0~10)는 스키마에 minimum/maximum 을 넣지 않고(strict 모드 호환) 프롬프트로
지시한 뒤 코드에서 clamp 한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["HIGH", "MEDIUM", "LOW"]

# 채점 기준 키 → 화면 표시 라벨. 결정론 코드가 의존하는 유일한 정본.
CRITERION_LABELS: dict[str, str] = {
    "grounding": "근거 충실성/환각",
    "temporal": "시간 정합성",
    "place": "장소 정합성",
    "coverage": "완결성",
    "composition": "사건 구성·하루 서사",
    "writing": "문장 품질(노출)",
    "question": "회고 질문",
    "overall": "전반",
}

# scores 안의 기준 순서(overall 제외).
CRITERION_KEYS: tuple[str, ...] = (
    "grounding",
    "temporal",
    "place",
    "coverage",
    "composition",
    "writing",
    "question",
)

METRIC_LABELS: dict[str, str] = {
    "groundedEventPrecision": "근거 event 정밀도",
    "hallucinatedEventRate": "환각 event 비율",
    "validSourceLinkRate": "유효 source 연결 비율",
    "coreEventRecall": "핵심 사건 재현율",
    "timelineF1": "타임라인 F1",
    "calendarCoverageRate": "Calendar 반영 비율",
    "photoAssignmentRate": "Photo 단일 귀속 비율",
    "temporalValidityRate": "시간 유효 event 비율",
    "meanTemporalIoU": "평균 시간 IoU",
    "meanBoundaryErrorMinutes": "평균 경계 오차(분)",
    "placeSupportRate": "장소 근거 비율",
    "compositionValidityRate": "구성 유효 event 비율",
    "durationComplianceRate": "지속시간 준수 비율",
    "titleComplianceRate": "제목 준수 비율",
    "descriptionComplianceRate": "설명 준수 비율",
    "writingComplianceRate": "문장 전체 준수 비율",
    "questionCoverageRate": "질문 존재 비율",
    "questionFormatRate": "질문 형식 유효 비율",
    "questionQualityRate": "질문 의미 품질 비율",
    "fullyValidQuestionRate": "완전 유효 질문 비율",
}
METRIC_KEYS: tuple[str, ...] = tuple(METRIC_LABELS)


class ScoreItem(BaseModel):
    score: int = Field(description="0~10 정수 (0=심각한 위반, 10=문제 없음)")
    reason: str = Field(description="점수 근거 한 줄(한국어)")


class RubricScores(BaseModel):
    grounding: ScoreItem = Field(description="근거 충실성/환각: 출력이 입력 근거에 기반하는가, 지어낸 것은 없는가")
    temporal: ScoreItem = Field(description="시간 정합성: 시각·순서가 window·수면·근거와 모순 없는가")
    place: ScoreItem = Field(description="장소 정합성: 장소/주소가 근거에 있고 잘못 붙지 않았는가")
    coverage: ScoreItem = Field(description="완결성: 주요 활동·일정 누락 없이 하루가 설명되는가")
    composition: ScoreItem = Field(description="사건 구성: 병합·분할·지속시간과 하루 서사가 자연스러운가")
    writing: ScoreItem = Field(description="문장 품질: 1인칭 해요체 과거형, 추정표현·원시수치 배제, 길이 적정")
    question: ScoreItem = Field(description="회고 질문: 모든 event 에 해요체 의문문·40자 내외 질문이 붙었는가")


class MetricResult(BaseModel):
    """v3 Metric 하나의 계산 결과와 재현 가능한 산식 근거."""

    value: float | None = Field(
        description="계산값. 비율·timelineF1은 0~100, meanTemporalIoU는 0~1, 경계 오차는 분 단위"
    )
    numerator: float | None = Field(description="분자 또는 평균 대상 값의 합. 계산 대상이 없으면 null")
    denominator: float | None = Field(description="분모 또는 평균 대상 수. 계산 대상이 없으면 null")
    reason: str = Field(description="분자·분모의 판정 근거 또는 null인 이유(한국어)")


class QuantitativeMetrics(BaseModel):
    """judge-rubric v3가 정의한 20개 정량 Metric."""

    groundedEventPrecision: MetricResult = Field(description="지지되는 출력 event 비율(%)")
    hallucinatedEventRate: MetricResult = Field(description="근거 없는 출력 event 비율(%)")
    validSourceLinkRate: MetricResult = Field(description="유효하고 관련 있는 sourceRefs 연결 비율(%)")
    coreEventRecall: MetricResult = Field(description="반영된 core evidence group 비율(%)")
    timelineF1: MetricResult = Field(description="grounding precision과 core event recall의 F1(%)")
    calendarCoverageRate: MetricResult = Field(description="반영되거나 합당한 warning으로 보존된 Calendar 비율(%)")
    photoAssignmentRate: MetricResult = Field(description="정확히 하나의 event에 귀속된 정상 Photo 비율(%)")
    temporalValidityRate: MetricResult = Field(description="시간 조건을 모두 만족하는 event 비율(%)")
    meanTemporalIoU: MetricResult = Field(description="직접 시간 구간과 대응 event의 평균 IoU(0~1)")
    meanBoundaryErrorMinutes: MetricResult = Field(description="직접 시간 구간 경계의 평균 오차(분)")
    placeSupportRate: MetricResult = Field(description="근거가 지지하는 명시적 장소 주장 비율(%)")
    compositionValidityRate: MetricResult = Field(description="구성 문제가 없는 event 비율(%)")
    durationComplianceRate: MetricResult = Field(description="지속시간 규칙을 만족하는 대상 event 비율(%)")
    titleComplianceRate: MetricResult = Field(description="제목 기준을 만족하는 event 비율(%)")
    descriptionComplianceRate: MetricResult = Field(description="설명 기준을 만족하는 event 비율(%)")
    writingComplianceRate: MetricResult = Field(description="제목과 설명 기준을 모두 만족하는 event 비율(%)")
    questionCoverageRate: MetricResult = Field(description="비어 있지 않은 질문 하나가 있는 event 비율(%)")
    questionFormatRate: MetricResult = Field(description="형식이 유효한 생성 질문 비율(%)")
    questionQualityRate: MetricResult = Field(description="의미 품질이 유효한 생성 질문 비율(%)")
    fullyValidQuestionRate: MetricResult = Field(description="존재·형식·품질을 모두 통과한 질문의 event 비율(%)")


class Finding(BaseModel):
    criterion: str = Field(
        description="관련 기준 키(grounding/temporal/place/coverage/composition/writing/question/overall)"
    )
    severity: Severity = Field(description="심각도")
    description: str = Field(description="문제 내용(한국어)")

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_legacy_medium(cls, value: str) -> str:
        """기존 저장 결과의 MED를 v4 표기인 MEDIUM으로 읽는다."""
        return "MEDIUM" if value == "MED" else value


class TraceScorecard(BaseModel):
    scores: RubricScores
    metrics: QuantitativeMetrics = Field(description="v3 정의에 따라 점수보다 먼저 계산한 20개 Metric")
    overall: ScoreItem = Field(description="전반: 하루 기록으로서의 종합 품질(0~10)")
    findings: list[Finding] = Field(description="발견한 문제점 목록(없으면 빈 리스트)")
    summary: str = Field(description="종합 평가 1~2문장(한국어)")
