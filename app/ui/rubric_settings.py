"""채점 기준 설정 — 평가 대상별 채점 항목을 여기서 고친다.

기본값은 메트릭 문서다. 이 화면에서 항목·배점·확인 기준을 고쳐 저장하면 그 내용이
`data/rubrics/<stageKey>.json` 에 남고, **다음 채점부터 그대로 채점 프롬프트가 된다**
(→ [app.analysis.stages.get][] → [app.analysis.stage_judge.system_prompt][]).

지키는 규칙은 저장할 때 검사한다: 배점 합계 100점, 항목 키는 중복 없는 식별자, 확인 기준은 비울 수
없음. 채점 결과의 field 이름이 항목 키라서, 키를 바꾸면 그 항목의 과거 점수와는 이어지지 않는다.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.analysis import rubric_store, stages
from app.ui import stage_view


def _document_rows(stage_key: str) -> list[dict[str, Any]]:
    """메트릭 문서 그대로의 항목. '되돌리기' 미리보기에 쓴다."""
    spec = stages.base(stage_key)
    return [
        {
            "key": entry.item.key,
            "label": entry.item.label,
            "points": entry.item.points,
            "criteria": entry.text,
        }
        for entry in stages.criteria(spec)
    ]


def render() -> None:
    st.title("채점 기준 설정")
    st.caption(
        "평가 대상별 채점 항목입니다. Task 리뷰 화면의 각 단계에서도 같은 표를 고칠 수 있습니다. "
        "저장하면 다음 채점부터 그대로 채점 프롬프트에 반영됩니다."
    )
    stage_view.inject_css()

    edited = rubric_store.edited_stages()
    labels = {
        spec.key: spec.label + (" · 수정됨" if spec.key in edited else "") for spec in stages.STAGES
    }
    stage_key = st.selectbox("평가 대상", options=list(labels), format_func=lambda key: labels[key])
    spec = stages.get(stage_key)

    head = st.columns(4)
    head[0].metric("배점 합계", f"{spec.total_points}/100")
    head[1].metric("항목 수", len(spec.items))
    head[2].metric("기준", "수정됨" if stage_key in edited else "문서 기본값")
    head[3].metric("트레이스", spec.trace_name)
    if stage_key in edited:
        st.caption(f"마지막 수정 {(rubric_store.updated_at(stage_key) or '')[:16]}")
    else:
        st.caption(
            f"메트릭 문서 {', '.join(spec.doc_sections)}절을 그대로 쓰고 있습니다. "
            "고쳐 저장하면 이 단계만 편집본으로 바뀝니다."
        )

    stage_view.render_criteria_editor(spec, state_key=f"rubric_settings_{stage_key}")

    with st.expander("메트릭 문서 기본값 보기", expanded=False):
        st.caption(
            "저장소의 기준 문서(`assets/rubrics/laimory-metric-v5.md`) 내용입니다. "
            "위 표를 고쳐도 이 문서는 바뀌지 않습니다."
        )
        stage_view.wrapped_table(
            [
                {"label": row["label"], "_num_points": row["points"], "criteria": row["criteria"]}
                for row in _document_rows(stage_key)
            ],
            (("label", "항목", 22), ("_num_points", "배점", 8), ("criteria", "확인 기준", 70)),
        )
