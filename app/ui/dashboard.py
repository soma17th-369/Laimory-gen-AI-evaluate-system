"""① 대시보드 — 공용 Langfuse 로그 스냅샷의 통계·총 사용량."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.storage import store
from app.storage.paths import collection_file


def render() -> None:
    st.title("📊 대시보드")
    st.caption("공용으로 수집된 LangFuse 로그 통계 · 총 사용량")

    rows = store.load_json(collection_file())
    if not rows:
        st.info("먼저 **LangFuse 로그 수집** 페이지에서 로그를 수집하세요.")
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
