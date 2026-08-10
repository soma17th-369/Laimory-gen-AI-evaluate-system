"""리포트 내보내기 (M3). json(그대로 직렬화) / markdown(사람이 읽는 형식)."""

from __future__ import annotations

import json

from app.analysis.schema import CRITERION_KEYS, CRITERION_LABELS
from app.report.schema import Report

_SEVERITIES = ("HIGH", "MED", "LOW")


def report_to_json(report: Report) -> str:
    """한글이 그대로 보이도록 ensure_ascii=False 로 직렬화."""
    return json.dumps(report.model_dump(), ensure_ascii=False, indent=2)


def _cell(text: str) -> str:
    """마크다운 표 셀용: 파이프·개행 이스케이프."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def report_to_markdown(report: Report) -> str:
    summary = report.summary
    avg_overall = summary.avg_overall if summary.avg_overall is not None else "-"

    lines: list[str] = [
        "# 채점 리포트",
        "",
        f"- judge 모델: `{report.judge_model}`",
        f"- 생성: {report.generated_at}",
        f"- 트레이스 수: {summary.trace_count}",
        f"- 평균 전반: {avg_overall}/10",
        "",
        "## 요약",
        "",
        "| 기준 | 평균 |",
        "| --- | --- |",
    ]
    for key in CRITERION_KEYS:
        lines.append(f"| {CRITERION_LABELS[key]} | {summary.avg_by_criterion.get(key, '-')}/10 |")
    lines.append(f"| **{CRITERION_LABELS['overall']}** | **{avg_overall}/10** |")
    lines += [
        "",
        "| 심각도 | 건수 |",
        "| --- | --- |",
    ]
    for sev in _SEVERITIES:
        lines.append(f"| {sev} | {summary.findings_by_severity.get(sev, 0)} |")

    lines += ["", "## 트레이스별"]
    for it in report.items:
        card = it.scorecard
        lines += [
            "",
            f"### {it.name or '(이름없음)'} · `{it.trace_id[:8]}` · {it.timestamp or ''}",
            f"- 전반 **{card.overall.score}/10** — {_cell(card.summary)}",
            "",
            "| 기준 | 점수 | 근거 |",
            "| --- | --- | --- |",
        ]
        for key in CRITERION_KEYS:
            item = getattr(card.scores, key)
            lines.append(f"| {CRITERION_LABELS[key]} | {item.score}/10 | {_cell(item.reason)} |")
        lines.append(
            f"| {CRITERION_LABELS['overall']} | {card.overall.score}/10 | {_cell(card.overall.reason)} |"
        )
        if card.findings:
            lines += ["", "문제점:"]
            for finding in card.findings:
                label = CRITERION_LABELS.get(finding.criterion, finding.criterion)
                lines.append(f"- [{finding.severity}] ({label}) {_cell(finding.description)}")

    return "\n".join(lines) + "\n"
