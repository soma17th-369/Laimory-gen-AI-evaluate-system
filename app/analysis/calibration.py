"""세부 기준 판정 → 고정 환산. LLM은 점수 대신 통과 건수와 근거를 반환한다."""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from app.analysis import stages

POLICY_VERSION = "criteria-ratio-v1"
ASSETS = Path(__file__).resolve().parents[2] / "assets" / "rubrics" / "calibration"


def checks(text: str) -> tuple[str, ...]:
    """최상위 bullet 하나(하위 조건 포함)를 한 기준으로 고정한다.

    User Memory 고정 필드 표는 데이터 행별로 나눈다. 설명·참조 표는 원문 프롬프트에 남으며
    별도 배점 기준으로 중복 계산하지 않는다. 자유문 편집본은 전체를 한 기준으로 사용한다.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"^[ ]{0,1}[-*] ", line)]
    if starts:
        result = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(lines)
            body = []
            for line in lines[start:end]:
                if line.strip().startswith(("코드 측정", "#", "|")):
                    break
                body.append(line)
            result.append("\n".join(body).strip().removeprefix("- ").removeprefix("* "))
        return tuple(result)
    rows = [line.strip() for line in lines if line.strip().startswith("| `")]
    return tuple(rows) if rows else (text.strip(),)


def definitions(spec: stages.StageSpec) -> dict[str, tuple[str, ...]]:
    return {entry.item.key: checks(entry.text) for entry in stages.criteria(spec)}


class CheckAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0, strict=True, description="이 기준에 해당하는 평가 단위 수. 없을 때만 0")
    passed: int = Field(ge=0, strict=True, description="모든 하위 조건을 충족한 평가 단위 수")
    failedRefs: list[str] = Field(description="실패 단위별 고유 ID 또는 field 경로. total-passed개")
    reason: str = Field(min_length=1, description="통과·실패 판정 근거. total=0이면 입력 부재 사유")

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.passed > self.total:
            raise ValueError("통과 수는 평가 수보다 클 수 없습니다")
        if len(self.failedRefs) != self.total - self.passed:
            raise ValueError("실패 단위마다 근거 위치가 하나씩 필요합니다")
        if len(set(self.failedRefs)) != len(self.failedRefs) or any(not ref.strip() for ref in self.failedRefs):
            raise ValueError("실패 근거 위치는 비어 있거나 중복될 수 없습니다")
        if not self.reason.strip():
            raise ValueError("판정 근거는 비어 있을 수 없습니다")
        return self


def result_model(spec: stages.StageSpec) -> type[BaseModel]:
    """편집된 확인 기준까지 스키마에 고정한다. 기준 누락·임의 기준 추가를 거부한다."""
    from app.analysis.stage_schema import Alert, Deduction

    item_fields = {}
    for key, texts in definitions(spec).items():
        check_model = create_model(
            f"{spec.key}_{key}_Checks",
            __config__=ConfigDict(extra="forbid"),
            **{f"c{i:02}": (CheckAssessment, ...) for i in range(1, len(texts) + 1)},
        )
        item_fields[key] = (check_model, ...)
    items = create_model(f"{spec.key}_Assessments", __config__=ConfigDict(extra="forbid"), **item_fields)
    return create_model(
        f"{spec.key}_CalibratedJudge",
        __config__=ConfigDict(extra="forbid"),
        items=(items, ...),
        deductions=(list[Deduction], ...),
        alerts=(list[Alert], ...),
        summary=(str, ...),
    )


def points_from_checks(points: int, assessments: list[CheckAssessment]) -> tuple[int, bool]:
    ratios = [Fraction(row.passed, row.total) for row in assessments if row.total]
    if not ratios:
        return 0, False
    value = points * sum(ratios) / len(ratios)
    # 항목별 정수 점수 계약 유지. 정확한 유리수 계산 후 .5 이상 올림(은행가 반올림 아님).
    rounded = (2 * value.numerator + value.denominator) // (2 * value.denominator)
    return rounded, True


def score(spec: stages.StageSpec, card: BaseModel, *, usage: dict | None = None):
    from app.analysis import stage_schema

    payload = card.model_dump()
    item_scores = {}
    for item in spec.items:
        item_card = getattr(card.items, item.key)
        rows = [getattr(item_card, key) for key in type(item_card).model_fields]
        points, applied = points_from_checks(item.points, rows)
        reason = "\n".join(
            f"c{i:02}: {row.passed}/{row.total} 통과 — {row.reason}"
            for i, row in enumerate(rows, 1)
        )
        item_scores[item.key] = {"score": points, "applied": applied, "reason": reason}
    legacy_shape = stage_schema.scorecard_model(spec.key).model_validate({**payload, "items": item_scores})
    return stage_schema.tally(
        spec, legacy_shape,
        extras={"usage": usage or {}, "scoringPolicy": POLICY_VERSION, "checks": payload["items"]},
    )


def prompt(spec: stages.StageSpec) -> str:
    blocks = [(ASSETS / "rules.md").read_text(encoding="utf-8")]
    by_key = definitions(spec)
    for item in spec.items:
        texts = by_key[item.key]
        blocks.append(f"### 판정 ID: {item.key} — {item.points}점")
        blocks.extend(f"- c{i:02}: {text}" for i, text in enumerate(texts, 1))
        examples = [
            points_from_checks(item.points, [CheckAssessment(total=5, passed=n, failedRefs=[f"E{i}" for i in range(5-n)], reason="합성 예시")])[0]
            for n in (5, 4, 0)
        ]
        blocks.append(
            f"환산 예시(모든 적용 기준의 통과율이 같은 합성 사례): 5/5 → {examples[0]}점, "
            f"4/5 → {examples[1]}점, 0/5 → {examples[2]}점. 모든 기준 0/0 → N/A."
        )
    # 편집본에는 원래 의미와 달라진 항목이 있을 수 있어 원본 전용 예시를 섞지 않는다.
    if not stages.is_edited(spec.key):
        blocks.append((ASSETS / f"{spec.key}.md").read_text(encoding="utf-8"))
    return "\n\n".join(blocks)
