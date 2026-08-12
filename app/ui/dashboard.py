"""① 대시보드 — 수집된 LangFuse 로그 통계·총 사용량.

'수집'은 LangFuse 에서 트레이스 요약을 가져와 data/collection.json 에 저장하고, 그 파일을
집계해 보여준다. (토큰 합계는 트레이스별 상세 조회가 필요해 후속에서 보강)
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import get_settings
from app.langfuse_client import LangfuseNotConfigured, list_traces, trace_summary
from app.storage import store
from app.storage.paths import collection_file


def _collect(limit: int) -> int:
    resp = list_traces(limit=limit)
    rows = []
    for trace in getattr(resp, "data", []) or []:
        summary = trace_summary(trace)
        ts = summary.get("timestamp")
        rows.append(
            {
                "id": summary.get("id"),
                "name": summary.get("name"),
                "timestamp": str(ts) if ts is not None else None,
                "user_id": summary.get("user_id"),
                "latency": summary.get("latency"),
                "total_cost": summary.get("total_cost"),
            }
        )
    store.save_json(collection_file(), rows)
    st.session_state["collection"] = rows
    return len(rows)


def render() -> None:
    st.title("📊 대시보드")
    st.caption("수집된 LangFuse 로그 통계 · 총 사용량")

    configured = get_settings().has_langfuse_credentials()
    with st.sidebar:
        st.subheader("수집")
        limit = st.number_input("수집 개수", min_value=1, max_value=500, value=100)
        if st.button("LangFuse 에서 수집", type="primary", disabled=not configured, width="stretch"):
            try:
                with st.spinner("수집 중…"):
                    n = _collect(int(limit))
                st.success(f"{n}건 수집·저장 완료")
            except LangfuseNotConfigured as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"수집 실패: {type(exc).__name__}: {exc}")
        if not configured:
            st.caption(".env 에 LANGFUSE 키를 설정하세요.")

    rows = st.session_state.get("collection")
    if rows is None:
        rows = store.load_json(collection_file())
    if not rows:
        st.info("사이드바에서 **LangFuse 에서 수집**을 눌러 로그를 모으세요.")
        return

    df = pd.DataFrame(rows)

    def _num(col: str) -> pd.Series:
        """컬럼이 없거나 비숫자여도 안전한 숫자 Series 반환."""
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return pd.Series([0.0] * len(df), index=df.index)

    cost = _num("total_cost")
    latency = _num("latency")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("트레이스 수", len(df))
    col2.metric("총 비용", f"{cost.sum():.3f}")
    col3.metric("평균 latency(s)", f"{latency.mean():.2f}" if len(df) else "-")
    col4.metric("이름 종류", int(df["name"].nunique()) if "name" in df.columns else 0)

    if "name" in df:
        st.subheader("이름별 분포")
        st.bar_chart(df["name"].value_counts())

    st.subheader("수집 목록")
    st.dataframe(df, width="stretch", hide_index=True)
