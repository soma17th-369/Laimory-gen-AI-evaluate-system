"""리포트 계약 (M3).

M2 의 `TraceScorecard` 를 트레이스 메타와 묶어 리포트로 조립한다. json 내보내기는 이 모델을
그대로 직렬화하고, md 는 [export][app.report.export] 가 포맷한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.analysis.schema import TraceScorecard


class ReportItem(BaseModel):
    """트레이스 1건의 리포트 항목: 메타 + 채점 결과."""

    trace_id: str
    name: str | None = None
    timestamp: str | None = None
    scorecard: TraceScorecard


class ReportSummary(BaseModel):
    """여러 트레이스 집계."""

    trace_count: int
    avg_overall: float | None = None
    avg_by_criterion: dict[str, float] = Field(default_factory=dict)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)


class Report(BaseModel):
    judge_model: str
    generated_at: str
    summary: ReportSummary
    items: list[ReportItem]
