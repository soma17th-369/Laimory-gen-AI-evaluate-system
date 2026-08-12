"""② Task 리뷰·채점 — task 별 로그 모아 처리과정 확인 + LLM judge + 프롬프트 모아 보기.

채점 결과는 data/evaluations/ 에, 모은 프롬프트는 data/tasks/<taskId>/prompts.json 에 저장한다.
(⛔ tasks/<taskId>/trace.json 의 상세 구조는 사용자 '안내용 파일'을 받아 확정 — 지금은 미저장)
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app.analysis.judge import find_final_timeline, score_trace
from app.analysis.schema import CRITERION_KEYS, CRITERION_LABELS
from app.config import get_settings
from app.improve.suggest import collect_generation_prompts
from app.langfuse_client import (
    LangfuseNotConfigured,
    get_trace,
    list_traces,
    observation_row,
    trace_summary,
)
from app.storage import store
from app.storage.paths import evaluation_file, task_prompts_file


def _domain_task_id(trace_detail: Any, trace_id: str) -> str:
    """도메인 taskId(수집 input 의 taskId) 우선, 없으면 LangFuse trace id."""
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
    except LangfuseNotConfigured as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001
        st.error(f"조회 실패: {type(exc).__name__}: {exc}")


def _judge_and_save(trace_id: str, task_id: str, detail: Any) -> None:
    try:
        with st.spinner("채점 중… (OpenAI)"):
            card = score_trace(detail)
        st.session_state.setdefault("tr_cards", {})[trace_id] = card
        saved = {"taskId": task_id, "traceId": trace_id, "name": getattr(detail, "name", None), "scorecard": card.model_dump()}
        store.save_json(evaluation_file(task_id), saved)
        st.toast(f"평가 저장: evaluations/{task_id}.json")
    except Exception as exc:  # noqa: BLE001
        st.error(f"채점 실패: {type(exc).__name__}: {exc}")


def _save_prompts(task_id: str, detail: Any) -> None:
    prompts = collect_generation_prompts(detail)
    store.save_json(task_prompts_file(task_id), {"taskId": task_id, "prompts": prompts})
    st.toast(f"프롬프트 저장: tasks/{task_id}/prompts.json")
    st.session_state.setdefault("tr_prompts", {})[task_id] = prompts


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

    st.divider()
    st.markdown(f"### {getattr(detail, 'name', None) or '(이름없음)'}  ·  task `{task_id}`")

    # 처리 과정: 최종 타임라인 + 관측치
    timeline = find_final_timeline(detail)
    observations = list(getattr(detail, "observations", []) or [])
    st.caption(f"관측치 {len(observations)}개 · 최종 타임라인 event {len(timeline.get('events', [])) if isinstance(timeline, dict) else 0}개")
    with st.expander("최종 타임라인(events)"):
        st.json(timeline if timeline is not None else {}, expanded=False)
    with st.expander("관측치 전체 처리과정"):
        st.dataframe(pd.DataFrame([observation_row(o) for o in observations]), width="stretch", hide_index=True)

    # 채점
    st.subheader("채점")
    if st.button("이 task 채점", disabled=not settings.has_openai_credentials(), key=f"judge_{selected}"):
        _judge_and_save(selected, task_id, detail)
    if not settings.has_openai_credentials():
        st.caption("채점하려면 .env 에 OPENAI_API_KEY 설정이 필요합니다.")
    card = st.session_state.get("tr_cards", {}).get(selected)
    if card is not None:
        _render_scorecard(card)

    # 프롬프트 모아 보기
    st.subheader("프롬프트 모아 보기")
    if st.button("프롬프트 수집·저장", key=f"prompts_{selected}"):
        _save_prompts(task_id, detail)
    prompts = st.session_state.get("tr_prompts", {}).get(task_id)
    if prompts:
        for p in prompts:
            with st.expander(f"{p['name']} (model={p['model']})"):
                for msg in p["messages"]:
                    st.markdown(f"**<{msg.get('role')}>**")
                    st.code(msg.get("content", ""))
