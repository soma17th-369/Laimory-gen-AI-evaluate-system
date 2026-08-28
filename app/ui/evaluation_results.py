"""저장된 채점 결과와 입출력 데이터를 함께 비교하는 페이지."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app.analysis.schema import CRITERION_KEYS, CRITERION_LABELS, METRIC_KEYS, METRIC_LABELS
from app.storage import store
from app.storage.paths import evaluations_dir, task_trace_file


_TABLE_CSS = """
<style>
.evaluation-wrap-table {
    width: 100%;
    margin: 0.35rem 0 1rem;
    overflow-x: clip;
}
.evaluation-wrap-table table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 0.86rem;
    line-height: 1.45;
}
.evaluation-wrap-table th,
.evaluation-wrap-table td {
    border: 1px solid rgba(128, 128, 128, 0.28);
    padding: 0.55rem 0.6rem;
    text-align: left;
    vertical-align: top;
    white-space: normal;
    word-break: keep-all;
    overflow-wrap: anywhere;
}
.evaluation-wrap-table th {
    background: rgba(128, 128, 128, 0.12);
    font-weight: 600;
}
</style>
"""


def _cell(value: Any) -> str:
    """채점 텍스트를 안전하게 HTML table cell로 만든다."""
    if value is None:
        return "-"
    return escape(str(value)).replace("\n", "<br>")


def _render_wrapped_table(
    rows: list[dict[str, Any]],
    columns: tuple[tuple[str, str, int], ...],
) -> None:
    """가로 스크롤 없이 셀 높이가 내용에 맞춰 늘어나는 표를 렌더링한다."""
    colgroup = "".join(f'<col style="width:{width}%">' for _, _, width in columns)
    header = "".join(f"<th>{escape(label)}</th>" for _, label, _ in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_cell(row.get(key))}</td>" for key, _, _ in columns) + "</tr>"
        for row in rows
    )
    st.markdown(
        f'<div class="evaluation-wrap-table"><table><colgroup>{colgroup}</colgroup>'
        f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _load_evaluations() -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in store.list_json(evaluations_dir()):
        data = store.load_json(path)
        if isinstance(data, dict) and isinstance(data.get("scorecard"), dict):
            records.append((path, data))
    return sorted(records, key=lambda item: item[0].stat().st_mtime, reverse=True)


def _overall_score(evaluation: dict[str, Any]) -> Any:
    return ((evaluation.get("scorecard") or {}).get("overall") or {}).get("score")


def _overview_rows(records: list[tuple[Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for path, evaluation in records:
        scorecard = evaluation.get("scorecard") or {}
        rows.append(
            {
                "taskId": evaluation.get("taskId") or path.stem,
                "name": evaluation.get("name"),
                "종합 점수": _overall_score(evaluation),
                "문제점": len(scorecard.get("findings") or []),
                "채점 시각": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return rows


def _input_output(evaluation: dict[str, Any]) -> tuple[Any, Any, str | None]:
    """신규 평가 내장 데이터 우선, 기존 평가는 저장된 trace.json으로 보완한다."""
    input_data = evaluation.get("inputData")
    output_data = evaluation.get("outputData")
    task_id = str(evaluation.get("taskId") or "")
    trace = store.load_json(task_trace_file(task_id)) if task_id else None
    if isinstance(trace, dict):
        if input_data is None:
            input_data = {"task": trace.get("task"), "source": trace.get("source")}
        if output_data is None:
            output_data = (trace.get("result") or {}).get("timeline")
            if output_data is None:
                output_data = trace.get("operation")
    fallback_prompt = evaluation.get("inputPrompt") if input_data is None else None
    return input_data, output_data, fallback_prompt


def _render_scorecard(scorecard: dict[str, Any]) -> None:
    overall = scorecard.get("overall") or {}
    st.markdown(
        f"**종합 {overall.get('score', '-')} / 10** — "
        f"{scorecard.get('summary') or overall.get('reason') or ''}"
    )

    scores = scorecard.get("scores") or {}
    rows = []
    for key in CRITERION_KEYS:
        item = scores.get(key) or {}
        rows.append(
            {
                "기준": CRITERION_LABELS[key],
                "점수": f"{item.get('score', '-')}/10",
                "근거": item.get("reason"),
            }
        )
    rows.append(
        {
            "기준": CRITERION_LABELS["overall"],
            "점수": f"{overall.get('score', '-')}/10",
            "근거": overall.get("reason"),
        }
    )
    _render_wrapped_table(
        rows,
        (("기준", "기준", 25), ("점수", "점수", 14), ("근거", "근거", 61)),
    )

    metrics = scorecard.get("metrics") or {}
    if metrics:
        with st.expander("정량 Metric 20개", expanded=True):
            _render_wrapped_table(
                [
                    {
                        "Metric": METRIC_LABELS[key],
                        "값": (metrics.get(key) or {}).get("value"),
                        "분자": (metrics.get(key) or {}).get("numerator"),
                        "분모": (metrics.get(key) or {}).get("denominator"),
                        "근거": (metrics.get(key) or {}).get("reason"),
                    }
                    for key in METRIC_KEYS
                ],
                (
                    ("Metric", "Metric", 27),
                    ("값", "값", 10),
                    ("분자", "분자", 10),
                    ("분모", "분모", 10),
                    ("근거", "근거", 43),
                ),
            )

    findings = scorecard.get("findings") or []
    if findings:
        st.markdown("**문제점**")
        _render_wrapped_table(
            [
                {
                    "기준": CRITERION_LABELS.get(item.get("criterion"), item.get("criterion")),
                    "심각도": item.get("severity"),
                    "설명": item.get("description"),
                }
                for item in findings
            ],
            (("기준", "기준", 24), ("심각도", "심각도", 17), ("설명", "설명", 59)),
        )
    else:
        st.success("발견된 문제점이 없습니다.")


def render() -> None:
    st.markdown(_TABLE_CSS, unsafe_allow_html=True)
    st.title("📋 채점 결과")
    st.caption("저장된 task 채점 결과를 모아보고, 채점에 사용한 Input과 Output을 비교합니다.")

    records = _load_evaluations()
    if not records:
        st.info("저장된 채점 결과가 없습니다. Task 리뷰·채점에서 먼저 채점을 실행하세요.")
        return

    st.subheader(f"저장된 결과 ({len(records)}건)")
    st.dataframe(pd.DataFrame(_overview_rows(records)), width="stretch", hide_index=True)

    paths = [path for path, _ in records]
    by_path = {path: evaluation for path, evaluation in records}
    selected_path = st.selectbox(
        "확인할 채점 결과",
        options=paths,
        format_func=lambda path: (
            f"{by_path[path].get('taskId') or path.stem} · "
            f"{by_path[path].get('name') or '(이름없음)'} · "
            f"{_overall_score(by_path[path])}/10"
        ),
    )
    evaluation = by_path[selected_path]
    scorecard = evaluation["scorecard"]
    task_id = evaluation.get("taskId") or selected_path.stem

    metric_cols = st.columns(4)
    metric_cols[0].metric("종합 점수", f"{_overall_score(evaluation)}/10")
    metric_cols[1].metric("문제점", len(scorecard.get("findings") or []))
    metric_cols[2].metric("Task", str(task_id)[:12])
    metric_cols[3].metric("Trace", str(evaluation.get("traceId") or "-")[:12])

    input_data, output_data, fallback_prompt = _input_output(evaluation)
    data_col, result_col = st.columns([1, 1], gap="small", vertical_alignment="top")
    with data_col:
        st.subheader("Input 데이터")
        if input_data is not None:
            st.json(input_data, expanded=2)
        elif fallback_prompt:
            st.caption("원본 Input이 없어 저장된 채점 입력 프롬프트를 표시합니다.")
            st.code(fallback_prompt)
        else:
            st.warning("저장된 Input 데이터가 없습니다.")

        st.subheader("Output 데이터")
        if output_data is not None:
            st.json(output_data, expanded=2)
        else:
            st.warning("저장된 Output 데이터가 없습니다.")

    with result_col:
        st.subheader("채점 결과")
        _render_scorecard(scorecard)

        rubric_ref = evaluation.get("rubricRef")
        if rubric_ref or evaluation.get("systemPrompt"):
            with st.expander("채점 기준 정보"):
                if rubric_ref:
                    st.json(rubric_ref)
                if evaluation.get("systemPrompt"):
                    st.code(evaluation["systemPrompt"])
