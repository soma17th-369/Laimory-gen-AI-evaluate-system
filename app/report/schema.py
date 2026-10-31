"""리포트 계약.

단계별 채점 결과(`data/evaluations/<taskId>.json`)를 Task 메타와 묶어 리포트로 조립한다.
json 내보내기는 이 모델을 그대로 직렬화하고, md 는 [export][app.report.export] 가 포맷한다.

점수의 단위는 **평가 대상 하나당 100점**이고, 종합은 채점된 대상들의 단순 평균이다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReportItem(BaseModel):
    """Task 1건의 리포트 항목: 메타 + 단계별 채점 결과 레코드."""

    task_id: str
    trace_id: str | None = None
    name: str | None = None
    timestamp: str | None = None
    composite: float | None = Field(default=None, description="종합 스코어(100점 만점)")
    record: dict[str, Any] = Field(description="evaluation_record 형식의 채점 결과 전체")


class ReportSummary(BaseModel):
    """여러 Task 집계."""

    task_count: int
    avg_composite: float | None = None
    avg_by_stage: dict[str, float] = Field(default_factory=dict)
    deductions_by_severity: dict[str, int] = Field(default_factory=dict)
    alerts_by_kind: dict[str, int] = Field(default_factory=dict)


class Report(BaseModel):
    judge_model: str
    generated_at: str
    summary: ReportSummary
    items: list[ReportItem]
