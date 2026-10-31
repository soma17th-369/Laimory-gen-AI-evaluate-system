"""리포트 조립. 단계별 채점 결과를 모아 평가 대상별 평균까지 계산한다."""

from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any

from app.analysis import evaluation_record, stages
from app.report.schema import Report, ReportItem, ReportSummary

_SEVERITIES = ("HIGH", "MEDIUM", "LOW")


def item_of(record: dict[str, Any], *, timestamp: str | None = None) -> ReportItem:
    """채점 결과 레코드 하나 → 리포트 항목."""
    return ReportItem(
        task_id=str(record.get("taskId") or "unknown"),
        trace_id=record.get("traceId"),
        name=record.get("traceName") or record.get("name"),
        timestamp=timestamp or record.get("updatedAt"),
        composite=evaluation_record.composite_score(record),
        record=record,
    )


def _summarize(items: list[ReportItem]) -> ReportSummary:
    if not items:
        return ReportSummary(task_count=0)

    composites = [item.composite for item in items if item.composite is not None]
    per_stage: dict[str, list[float]] = {}
    by_severity = {severity: 0 for severity in _SEVERITIES}
    by_kind: dict[str, int] = {}
    for item in items:
        for key, entry in (item.record.get("stages") or {}).items():
            card = entry.get("scorecard") or {}
            if isinstance(card.get("total"), (int, float)):
                per_stage.setdefault(key, []).append(float(card["total"]))
            for deduction in card.get("deductions") or []:
                severity = str(deduction.get("severity"))
                by_severity[severity] = by_severity.get(severity, 0) + 1
            for alert in card.get("alerts") or []:
                kind = str(alert.get("kind"))
                by_kind[kind] = by_kind.get(kind, 0) + 1

    return ReportSummary(
        task_count=len(items),
        avg_composite=round(mean(composites), 1) if composites else None,
        avg_by_stage={
            key: round(mean(values), 1)
            for key, values in sorted(per_stage.items(), key=lambda pair: stages.STAGE_KEYS.index(pair[0]))
        },
        deductions_by_severity=by_severity,
        alerts_by_kind=by_kind,
    )


def build_report(items: list[ReportItem], *, judge_model: str) -> Report:
    """채점 항목들 → 집계 포함 Report. `generated_at` 은 조립 시각(로컬)."""
    return Report(
        judge_model=judge_model,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        summary=_summarize(items),
        items=items,
    )
