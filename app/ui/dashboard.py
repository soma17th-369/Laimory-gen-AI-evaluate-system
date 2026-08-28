"""① 대시보드 — 공용 Langfuse 로그 스냅샷의 통계·총 사용량.

수집된 프로젝트(개발·운영)를 **한 목록으로** 본다(→ [app.environments][]). 어디서 온 로그인지는
`env` 열로 구분하고, 건수는 환경별로도 함께 보여준다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import environments
from app.storage import store
from app.storage.paths import collection_file


def render() -> None:
    st.title("📊 대시보드")
    st.caption("공용으로 수집된 LangFuse 로그 통계 · 총 사용량 (개발·운영 합계)")

    rows = store.load_json(collection_file())
    if not rows:
        st.info("먼저 **LangFuse 로그 수집** 페이지에서 로그를 수집하세요.")
        return

    df = pd.DataFrame(rows)
    # 환경 구분이 생기기 전 행에는 env 가 없다. 그때는 개발 프로젝트 하나만 보고 있었다.
    df["env"] = df["env"].fillna(environments.DEV) if "env" in df.columns else environments.DEV

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

    env_counts = df["env"].value_counts()
    env_cols = st.columns(len(environments.ENVIRONMENTS))
    for column, env in zip(env_cols, environments.ENVIRONMENTS):
        column.metric(environments.label(env), f"{int(env_counts.get(env, 0)):,}")

    if "name" in df:
        st.subheader("이름별 분포")
        st.bar_chart(df["name"].value_counts())

    st.subheader("수집 목록")
    st.caption("환경과 무관하게 최신순입니다. `env` 열이 개발/운영을 구분합니다.")
    st.dataframe(df, width="stretch", hide_index=True)
