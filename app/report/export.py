"""리포트 내보내기. json(그대로 직렬화) / markdown(사람이 읽는 형식)."""

from __future__ import annotations

import json

from app.analysis import stages
from app.report.schema import Report

_SEVERITIES = ("HIGH", "MEDIUM", "LOW")


def report_to_json(report: Report) -> str:
    """한글이 그대로 보이도록 ensure_ascii=False 로 직렬화."""
    return json.dumps(report.model_dump(), ensure_ascii=False, indent=2)


def _cell(text: str | None) -> str:
    """마크다운 표 셀용: 파이프·개행 이스케이프."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _stage_label(key: str) -> str:
    try:
        return stages.get(key).label
    except KeyError:
        return key


def report_to_markdown(report: Report) -> str:
    summary = report.summary
    avg = summary.avg_composite if summary.avg_composite is not None else "-"

    lines: list[str] = [
        "# 채점 리포트",
        "",
        f"- judge 모델: `{report.judge_model}`",
        f"- 생성: {report.generated_at}",
        f"- Task 수: {summary.task_count}",
        f"- 평균 종합: {avg}/100",
        "",
        "## 평가 대상별 평균",
        "",
        "| 평가 대상 | 평균 |",
        "| --- | ---: |",
    ]
    for key, value in summary.avg_by_stage.items():
        lines.append(f"| {_stage_label(key)} | {value}/100 |")

    lines += ["", "| 감점 심각도 | 건수 |", "| --- | ---: |"]
    for severity in _SEVERITIES:
        lines.append(f"| {severity} | {summary.deductions_by_severity.get(severity, 0)} |")
    if summary.alerts_by_kind:
        lines += ["", "| 별도 알림 | 건수 |", "| --- | ---: |"]
        for kind, count in summary.alerts_by_kind.items():
            lines.append(f"| {kind} | {count} |")

    lines += ["", "## Task 별"]
    for item in report.items:
        composite = item.composite if item.composite is not None else "-"
        lines += [
            "",
            f"### {item.name or '(이름없음)'} · task `{item.task_id[:8]}` · {item.timestamp or ''}",
            f"- 종합 **{composite}/100**",
            "",
            "| 평가 대상 | 총점 | 요약 |",
            "| --- | ---: | --- |",
        ]
        for key, entry in (item.record.get("stages") or {}).items():
            card = entry.get("scorecard") or {}
            total = card.get("total")
            lines.append(
                f"| {_stage_label(key)} | {total if total is not None else 'N/A'} | "
                f"{_cell(card.get('summary') or card.get('skipReason'))} |"
            )
        for key, entry in (item.record.get("stages") or {}).items():
            card = entry.get("scorecard") or {}
            if card.get("total") is None:
                continue
            lines += [
                "",
                f"#### {_stage_label(key)} 항목별 점수",
                "",
                "| 항목 | 점수 | 이유 |",
                "| --- | ---: | --- |",
            ]
            for score_item in card.get("items") or []:
                value = (
                    f"{score_item.get('score')}/{score_item.get('points')}"
                    if score_item.get("applied")
                    else "N/A"
                )
                lines.append(f"| {score_item.get('label')} | {value} | {_cell(score_item.get('reason'))} |")
            deductions = card.get("deductions") or []
            if deductions:
                lines += ["", "감점 근거:"]
                for deduction in deductions:
                    refs = ", ".join(deduction.get("sourceRefs") or []) or "-"
                    lines.append(
                        f"- [{deduction.get('severity')}] ({deduction.get('itemKey')}) "
                        f"{_cell(deduction.get('description'))} · 입력 {refs} · 출력 {deduction.get('outputPath')}"
                    )
            alerts = card.get("alerts") or []
            for alert in alerts:
                lines.append(
                    f"- [ALERT/{alert.get('kind')}] {alert.get('where')} — {_cell(alert.get('detail'))}"
                )

    return "\n".join(lines) + "\n"
