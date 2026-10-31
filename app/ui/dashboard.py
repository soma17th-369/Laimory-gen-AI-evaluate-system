"""① 대시보드 — 공용 Langfuse 로그 스냅샷의 통계·총 사용량.

수집된 프로젝트(개발·운영)를 **한 목록으로** 본다(→ [app.environments][]). 어디서 온 로그인지는
`env` 열로 구분하고, 두 환경을 함께 볼 때는 건수를 환경별로도 보여준다. 환경 필터
(→ [app.ui.env_filter][])로 한 환경을 고르면 통계·목록이 모두 그 환경 것만 집계된다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import environments
from app.storage import store
from app.storage.paths import collection_file
from app.ui import env_filter


def render() -> None:
    st.title("대시보드")
    st.caption("공용으로 수집된 LangFuse 로그 통계 · 총 사용량")

    rows = store.load_json(collection_file())
    if not rows:
        st.info("먼저 **LangFuse 로그 수집** 페이지에서 로그를 수집하세요.")
        return

    envs = env_filter.pick()
    rows = environments.keep(rows, envs)
    if not rows:
        st.info(f"{env_filter.scope_label(envs)}에서 수집된 로그가 없습니다.")
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

    st.caption(f"집계 범위: {env_filter.scope_label(envs)}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("트레이스 수", len(df))
    col2.metric("총 비용", f"{cost.sum():.3f}")
    col3.metric("평균 latency(s)", f"{latency.mean():.2f}" if len(df) else "-")
    col4.metric("이름 종류", int(df["name"].nunique()) if "name" in df.columns else 0)

    # 한 환경만 볼 때는 환경별 건수가 트레이스 수와 같으므로 두 환경 이상일 때만 나눠 보인다.
    if len(envs) > 1:
        env_counts = df["env"].value_counts()
        env_cols = st.columns(len(envs))
        for column, env in zip(env_cols, envs):
            column.metric(environments.label(env), f"{int(env_counts.get(env, 0)):,}")

    if "name" in df:
        st.subheader("이름별 분포")
        st.bar_chart(df["name"].value_counts())

    st.subheader("수집 목록")
    st.caption("최신순입니다. `env` 열이 어느 프로젝트에서 온 로그인지 알려줍니다.")
    st.dataframe(df, width="stretch", hide_index=True)
