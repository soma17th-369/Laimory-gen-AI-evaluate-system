"""리포트 조립 (M3). 채점된 항목들을 모아 집계까지 계산한다."""

from __future__ import annotations

from datetime import datetime
from statistics import mean

from app.analysis.schema import CRITERION_KEYS
from app.report.schema import Report, ReportItem, ReportSummary

_SEVERITIES = ("HIGH", "MED", "LOW")


def _summarize(items: list[ReportItem]) -> ReportSummary:
    if not items:
        return ReportSummary(trace_count=0)

    overalls = [it.scorecard.overall.score for it in items]
    avg_by_criterion = {
        key: round(mean(getattr(it.scorecard.scores, key).score for it in items), 2)
        for key in CRITERION_KEYS
    }
    by_severity = {sev: 0 for sev in _SEVERITIES}
    for it in items:
        for finding in it.scorecard.findings:
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1

    return ReportSummary(
        trace_count=len(items),
        avg_overall=round(mean(overalls), 2),
        avg_by_criterion=avg_by_criterion,
        findings_by_severity=by_severity,
    )


def build_report(items: list[ReportItem], *, judge_model: str) -> Report:
    """채점 항목들 → 집계 포함 Report. `generated_at` 은 조립 시각(로컬)."""
    return Report(
        judge_model=judge_model,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        summary=_summarize(items),
        items=items,
    )
