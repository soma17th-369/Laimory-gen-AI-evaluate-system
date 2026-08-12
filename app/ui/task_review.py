"""② Task 리뷰·채점 — task 별 전체 처리과정을 중복 없는 trace.json 으로 재구성해 보고 저장.

처리과정(steps)·최종 타임라인(result)·프롬프트(generations)를 명세 구조로 보여주고,
`data/tasks/<taskId>/trace.json` 에 저장한다(프롬프트는 §14 권고대로 trace.json 통합).
채점 결과는 `data/evaluations/<taskId>.json`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app.analysis.judge import assemble_evidence, score_trace
from app.analysis.rubric import SYSTEM_PROMPT, build_user_prompt
from app.analysis.schema import CRITERION_KEYS, CRITERION_LABELS
from app.config import get_settings
from app.langfuse_client import LangfuseNotConfigured, get_trace, list_traces, trace_summary
from app.storage import store
from app.storage.paths import evaluation_file, task_trace_file
from app.tasks.trace_builder import build_trace_json


def _domain_task_id(trace_detail: Any, trace_id: str) -> str:
    raw = getattr(trace_detail, "input", None)
    if isinstance(raw, dict):
        tid = raw.get("taskId") or (raw.get("request") or {}).get("taskId")
        if tid:
            return str(tid)
    return trace_id


def _render_scorecard(card: Any) -> None:
    st.markdown(f"**종합 {card.overall.score} / 10** — {card.summary}")
    rows = [
        {"기준": CRITERION_LABELS[k], "점수": f"{getattr(card.scores, k).score}/10", "근거": getattr(card.scores, k).reason}
        for k in CRITERION_KEYS
    ]
    rows.append({"기준": CRITERION_LABELS["overall"], "점수": f"{card.overall.score}/10", "근거": card.overall.reason})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    if card.findings:
        st.markdown("**문제점**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"기준": CRITERION_LABELS.get(f.criterion, f.criterion), "심각도": f.severity, "설명": f.description}
                    for f in card.findings
                ]
            ),
            width="stretch",
            hide_index=True,
        )


def _fetch(limit: int, name: str, user_id: str) -> None:
    try:
        with st.spinner("트레이스 조회 중…"):
            resp = list_traces(limit=limit, name=name, user_id=user_id)
        st.session_state["tr_traces"] = list(getattr(resp, "data", []) or [])
        st.session_state["tr_detail"] = {}
        st.session_state["tr_tracejson"] = {}
    except LangfuseNotConfigured as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001
        st.error(f"조회 실패: {type(exc).__name__}: {exc}")


def _judge_and_save(trace_id: str, task_id: str, detail: Any, system_prompt: str) -> None:
    try:
        with st.spinner("채점 중… (OpenAI)"):
            card = score_trace(detail, system_prompt=system_prompt)
        st.session_state.setdefault("tr_cards", {})[trace_id] = card
        path = evaluation_file(task_id)
        store.save_json(
            path,
            {
                "taskId": task_id,
                "traceId": trace_id,
                "name": getattr(detail, "name", None),
                "systemPrompt": system_prompt,  # 채점 기준(편집본)
                "inputPrompt": build_user_prompt(assemble_evidence(detail)),  # 채점 입력 프롬프트
                "scorecard": card.model_dump(),  # 결과
            },
        )
        st.session_state["tr_saved_path"] = path.as_posix()
        st.toast(f"평가 저장: {path.as_posix()}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"채점 실패: {type(exc).__name__}: {exc}")


def _render_process(tj: dict) -> None:
    steps = tj["process"]["steps"]
    generations = tj["process"]["generations"]

    with st.expander(f"처리 과정 (steps {len(steps)}개, 실행 순서)", expanded=True):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "순서": s["order"],
                        "단계": s["name"],
                        "유형": s["type"],
                        "입력참조": ", ".join(s["inputRefs"]),
                        "GEN": len(s["generationRefs"]),
                    }
                    for s in steps
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    with st.expander("최종 타임라인 (result.timeline)"):
        st.json(tj["result"]["timeline"] or {}, expanded=False)

    with st.expander(f"프롬프트 (generations {len(generations)}개)"):
        if not generations:
            st.caption("이 트레이스에는 GENERATION 관측치가 없습니다.")
        for gen in generations:
            st.markdown(f"**{gen['name']}** · `{gen['model']}`")
            for msg in gen.get("input") or []:
                if isinstance(msg, dict):
                    st.caption(f"<{msg.get('role')}>")
                    st.code(str(msg.get("content", ""))[:4000])


def render() -> None:
    st.title("🔍 Task 리뷰·채점")
    settings = get_settings()

    with st.sidebar:
        st.subheader("조회 필터")
        limit = st.number_input("개수", min_value=1, max_value=100, value=25)
        name = st.text_input("이름(name)", value="")
        user_id = st.text_input("user_id", value="")
        if st.button("트레이스 조회", type="primary", width="stretch", disabled=not settings.has_langfuse_credentials()):
            _fetch(int(limit), name, user_id)

    traces = st.session_state.get("tr_traces")
    if not traces:
        st.info("사이드바에서 **트레이스 조회**를 누르세요.")
        return

    summaries = [trace_summary(t) for t in traces]
    id_to_summary = {s["id"]: s for s in summaries}
    st.dataframe(pd.DataFrame(summaries), width="stretch", hide_index=True)

    selected = st.selectbox(
        "상세 볼 트레이스",
        options=list(id_to_summary.keys()),
        format_func=lambda i: f"{id_to_summary[i].get('name')} · {str(i)[:8]}",
    )
    if not selected:
        return

    detail_cache = st.session_state.setdefault("tr_detail", {})
    if selected not in detail_cache:
        try:
            with st.spinner("상세 조회 중…"):
                detail_cache[selected] = get_trace(selected)
        except Exception as exc:  # noqa: BLE001
            st.error(f"상세 조회 실패: {type(exc).__name__}: {exc}")
            return
    detail = detail_cache[selected]
    task_id = _domain_task_id(detail, selected)

    tj_cache = st.session_state.setdefault("tr_tracejson", {})
    if selected not in tj_cache:
        tj_cache[selected] = build_trace_json(detail)
    tj = tj_cache[selected]

    st.divider()
    st.markdown(f"### {getattr(detail, 'name', None) or '(이름없음)'}  ·  task `{task_id}`")
    cols = st.columns(4)
    cols[0].metric("관측치", tj["langfuse"]["observationCount"])
    cols[1].metric("처리 단계", len(tj["process"]["steps"]))
    cols[2].metric("LLM 호출", len(tj["process"]["generations"]))
    cols[3].metric("최종 event", len((tj["result"]["timeline"] or {}).get("events") or []))

    if st.button("처리과정 저장 (trace.json)", key=f"save_{selected}"):
        store.save_json(task_trace_file(task_id), tj)
        st.toast(f"저장: tasks/{task_id}/trace.json")

    _render_process(tj)

    st.subheader("채점")
    system_prompt = st.text_area(
        "채점 기준 (system prompt · 편집 가능)",
        value=SYSTEM_PROMPT,
        height=280,
        key=f"rubric_{selected}",
        help="편집하면 이 기준으로 채점합니다. 점수 항목(6기준+전반)은 스키마로 고정됩니다.",
    )
    with st.expander("채점 입력 프롬프트 (judge 에 들어가는 근거)"):
        st.code(build_user_prompt(assemble_evidence(detail)))

    if st.button("이 task 채점", type="primary", disabled=not settings.has_openai_credentials(), key=f"judge_{selected}"):
        _judge_and_save(selected, task_id, detail, system_prompt)
    if not settings.has_openai_credentials():
        st.caption("채점하려면 .env 에 OPENAI_API_KEY 설정이 필요합니다.")

    saved_path = st.session_state.get("tr_saved_path")
    if saved_path:
        st.caption(f"저장 위치: `{saved_path}` (기준·입력 프롬프트·결과 포함)")

    card = st.session_state.get("tr_cards", {}).get(selected)
    if card is not None:
        _render_scorecard(card)
