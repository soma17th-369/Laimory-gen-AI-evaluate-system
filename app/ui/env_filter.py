"""환경 필터 — 로그를 보여주는 모든 화면이 같이 쓰는 개발·운영 선택.

목록은 여전히 **한 목록**이다(→ [app.environments][]). 기본값 `전체`는 두 프로젝트를 합쳐 보고, 한
환경을 고르면 그 화면의 목록·건수·통계가 그 환경 것만 남는다. 거르는 판단은
[environments.keep][app.environments.keep] 하나로 한다.

선택은 세션 동안 **페이지를 옮겨도 유지된다**. 한 번 운영을 고르면 대시보드·Task 리뷰·채점 결과
등 모든 화면이 같은 범위를 본다. 수집(동기화)은 필터와 무관하게 키가 설정된 환경을 모두 받는다.
"""

from __future__ import annotations

import streamlit as st

from app import environments

ALL = "all"
"""두 환경을 합쳐 보는 기본 선택."""

_KEY = "env_filter"
"""모든 페이지가 같은 key 를 써서 선택을 공유한다."""


def envs_for(choice: str | None) -> tuple[str, ...]:
    """필터 값 → 보여줄 환경. `전체`(또는 알 수 없는 값)는 모든 환경이다."""
    if choice in environments.ENVIRONMENTS:
        return (str(choice),)
    return environments.ENVIRONMENTS


def scope_label(envs: tuple[str, ...]) -> str:
    """캡션용 범위 표기. 모든 환경이면 합계라고 적는다."""
    if tuple(envs) == environments.ENVIRONMENTS:
        return "개발·운영 합계"
    return " · ".join(environments.label(env) for env in envs)


def _option_label(choice: str) -> str:
    return "전체" if choice == ALL else environments.label(choice)


def pick() -> tuple[str, ...]:
    """환경 필터를 그리고 고른 환경을 돌려준다."""
    choice = st.segmented_control(
        "환경",
        options=(ALL, *environments.ENVIRONMENTS),
        default=ALL,
        required=True,
        format_func=_option_label,
        key=_KEY,
        persist_state="session",
    )
    return envs_for(choice)
