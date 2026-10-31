"""단계 채점 결과 계약과 총점 계산.

문서가 요구하는 것 둘을 코드가 보장한다.

1. **항목마다 점수와 이유.** 결과 모델을 배점표에서 만들기 때문에 항목이 하나라도 빠지면 스키마
   검증에서 실패한다. `reason` 은 빈 값을 허용하지 않는다(만점이어도 무엇을 확인했는지 적는다).
2. **항목별 점수의 합 = 총점.** 총점은 LLM 이 아니라 [tally][app.analysis.stage_schema.tally] 가
   계산한다. 평가할 입력이 없어 `applied=false` 인 항목의 배점은 문서 규칙대로 나머지 항목에
   비례 배분한다.

모델은 단계마다 다르므로 `create_model` 로 배점표에서 만들어 캐시한다. 항목 키가 곧 field 이름이라
provider 의 strict JSON Schema 가 항목 누락·오타를 막아 준다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model, field_validator

from app.analysis import stages
from app.analysis.stages import StageSpec

Severity = Literal["HIGH", "MEDIUM", "LOW"]
AlertKind = Literal["HALLUCINATION", "MISSING_SOURCE", "SENSITIVE"]

ALERT_LABELS: dict[str, str] = {
    "HALLUCINATION": "입력에서 확인되지 않는 사실",
    "MISSING_SOURCE": "필수 반영 source 누락",
    "SENSITIVE": "민감정보 노출",
}
"""문서가 "점수와 별개로 명시"하라고 한 3종. 점수와 따로 모아 화면 맨 위에 띄운다."""


class ItemScore(BaseModel):
    """채점 항목 하나의 결과."""

    score: int = Field(description="이 항목에서 받은 점수(0 ~ 배점). 배점을 넘기지 않는다")
    applied: bool = Field(
        description="이 항목을 평가할 입력이 있었는지. 없으면 false 로 두고 감점하지 않는다"
    )
    reason: str = Field(
        description="점수 근거(한국어). 감점했으면 어느 확인 기준을 못 지켰는지, 만점이면 무엇을 확인했는지 적는다"
    )

    @field_validator("reason")
    @classmethod
    def reason_is_required(cls, value: str) -> str:
        if not (value or "").strip():
            raise ValueError("항목마다 점수 이유를 적어야 한다")
        return value


class Deduction(BaseModel):
    """감점 하나. 입력·출력의 어디를 보고 감점했는지 남긴다."""

    itemKey: str = Field(description="감점한 항목 키(배점표의 항목 키)")
    severity: Severity = Field(description="심각도")
    description: str = Field(description="무엇이 문제인지(한국어)")
    sourceRefs: list[str] = Field(description="근거가 된 입력 rawId 목록. 없으면 빈 리스트")
    outputPath: str = Field(
        description="문제가 난 출력 위치. 예: events[2].description, candidates[0].places"
    )


class Alert(BaseModel):
    """점수와 별개로 반드시 알려야 하는 사건."""

    kind: AlertKind = Field(description="HALLUCINATION | MISSING_SOURCE | SENSITIVE")
    where: str = Field(description="입력 rawId 또는 출력 위치")
    detail: str = Field(description="무엇이 확인되지 않았는지·무엇이 누락·노출됐는지(한국어)")


def _signature(spec: StageSpec) -> tuple[tuple[str, str, int], ...]:
    """모델 캐시 키. 설정 화면에서 항목을 고치면 값이 바뀌어 새 모델이 만들어진다."""
    return tuple((item.key, item.label, item.points) for item in spec.items)


def items_model(stage_key: str) -> type[BaseModel]:
    """배점표에서 만든 항목 모델. 항목 키가 field 이름이 된다."""
    spec = stages.get(stage_key)
    return _items_model(stage_key, _signature(spec))


@lru_cache(maxsize=None)
def _items_model(stage_key: str, signature: tuple[tuple[str, str, int], ...]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        key: (ItemScore, Field(description=f"{label} (배점 {points}점)"))
        for key, label, points in signature
    }
    return create_model(f"{_camel(stage_key)}Items", **fields)


def scorecard_model(stage_key: str) -> type[BaseModel]:
    """단계 하나의 채점 결과 모델. provider 의 structured output 계약이다."""
    spec = stages.get(stage_key)
    return _scorecard_model(stage_key, spec.label, _signature(spec))


@lru_cache(maxsize=None)
def _scorecard_model(
    stage_key: str, label: str, signature: tuple[tuple[str, str, int], ...]
) -> type[BaseModel]:
    return create_model(
        f"{_camel(stage_key)}Scorecard",
        items=(
            _items_model(stage_key, signature),
            Field(description=f"{label} 의 모든 채점 항목. 하나도 빠뜨리지 않는다"),
        ),
        deductions=(list[Deduction], Field(description="감점 근거 목록(없으면 빈 리스트)")),
        alerts=(list[Alert], Field(description="점수와 별개로 명시할 사건(없으면 빈 리스트)")),
        summary=(str, Field(description="이 단계의 종합 평가 1~2문장(한국어)")),
    )


def _camel(stage_key: str) -> str:
    return "".join(part.capitalize() for part in stage_key.replace("_", "-").split("-"))


@dataclass(frozen=True)
class ScoredItem:
    """총점 계산까지 끝난 항목 하나."""

    key: str
    label: str
    score: int
    points: int
    """문서 배점."""
    applied_points: float
    """재배분 후 실제로 반영된 배점. 미평가 항목은 0."""
    applied: bool
    reason: str


@dataclass(frozen=True)
class StageScore:
    """단계 하나의 최종 채점 결과. 화면·저장이 함께 쓰는 형태."""

    stage_key: str
    label: str
    total: float | None
    items: tuple[ScoredItem, ...]
    deductions: tuple[dict[str, Any], ...] = ()
    alerts: tuple[dict[str, Any], ...] = ()
    summary: str = ""
    skip_reason: str | None = None
    redistributed: tuple[str, ...] = ()
    """평가 입력이 없어 배점을 나눠준 항목 키."""

    extras: dict[str, Any] = field(default_factory=dict)
    """점수와 무관한 기록: `usage` — 대상 서버가 이 단계에 쓴 토큰·시간."""

    @property
    def evaluated(self) -> bool:
        return self.total is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stageKey": self.stage_key,
            "label": self.label,
            "total": self.total,
            "items": [
                {
                    "key": item.key,
                    "label": item.label,
                    "score": item.score,
                    "points": item.points,
                    "appliedPoints": item.applied_points,
                    "applied": item.applied,
                    "reason": item.reason,
                }
                for item in self.items
            ],
            "deductions": list(self.deductions),
            "alerts": list(self.alerts),
            "summary": self.summary,
            "skipReason": self.skip_reason,
            "redistributed": list(self.redistributed),
            "usage": self.extras.get("usage") or {},
            "scoringPolicy": self.extras.get("scoringPolicy"),
            "checks": self.extras.get("checks") or {},
        }


def skipped(spec: StageSpec, reason: str, *, usage: dict[str, Any] | None = None) -> StageScore:
    """채점하지 않은 단계. 0점이 아니라 총점 없음으로 남긴다."""
    return StageScore(
        spec.key, spec.label, None, (), summary="", skip_reason=reason, extras={"usage": usage or {}}
    )


def tally(spec: StageSpec, card: BaseModel, *, extras: dict[str, Any] | None = None) -> StageScore:
    """LLM 결과 → 점수 계산이 끝난 결과.

    `applied=false` 항목의 배점은 나머지 항목에 비례 배분한다(문서 규칙). 그래서 총점은 항상
    100점 만점이고, 항목별 반영 배점의 합과 정확히 맞는다.
    """
    raw_items = card.items
    applied_points = sum(
        item.points for item in spec.items if getattr(raw_items, item.key).applied
    )
    scored: list[ScoredItem] = []
    redistributed: list[str] = []
    for item in spec.items:
        value = getattr(raw_items, item.key)
        score = max(0, min(item.points, int(value.score)))
        if not value.applied:
            redistributed.append(item.key)
            scored.append(ScoredItem(item.key, item.label, 0, item.points, 0.0, False, value.reason))
            continue
        share = round(item.points * stages.TOTAL_POINTS / applied_points, 2) if applied_points else 0.0
        scored.append(ScoredItem(item.key, item.label, score, item.points, share, True, value.reason))

    total = (
        round(
            sum(item.score for item in scored if item.applied) * stages.TOTAL_POINTS / applied_points,
            1,
        )
        if applied_points
        else None
    )
    return StageScore(
        stage_key=spec.key,
        label=spec.label,
        total=total,
        items=tuple(scored),
        deductions=tuple(item.model_dump() for item in card.deductions),
        alerts=tuple(item.model_dump() for item in card.alerts),
        summary=card.summary,
        skip_reason=None if applied_points else "모든 항목에 평가할 입력이 없었습니다.",
        redistributed=tuple(redistributed),
        extras=dict(extras or {}),
    )


def composite(scores: list[StageScore]) -> dict[str, Any]:
    """종합 스코어 = 채점된 평가 대상들의 단순 평균(문서 규칙). 미채점 대상은 제외한다."""
    evaluated = [score for score in scores if score.evaluated]
    return {
        "score": round(sum(score.total for score in evaluated) / len(evaluated), 1) if evaluated else None,
        "stageScores": {score.stage_key: score.total for score in evaluated},
        "skipped": {
            score.stage_key: score.skip_reason for score in scores if not score.evaluated
        },
        "evaluatedCount": len(evaluated),
    }
