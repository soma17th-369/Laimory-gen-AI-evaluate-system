"""Streamlit 진입점.

로컬 실행:

    uv run streamlit run app/main.py

`streamlit run` 은 이 파일이 있는 디렉터리(app/)를 sys.path 에 넣으므로, 패키지 경로
(`app.config`)로 import 하려면 프로젝트 루트를 경로에 추가한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> None:
    st.set_page_config(
        page_title="Laimory 생성형 AI 평가",
        page_icon="🔍",
        layout="wide",
    )

    st.title("Laimory 생성형 AI 평가 도구")
    st.caption("LangFuse 로그 분석 · 점수 · 문제점 · 프롬프트 개선 · 테스트 데이터 생성")

    settings = get_settings()
    with st.sidebar:
        st.header("연결 상태")
        if settings.has_langfuse_credentials():
            st.success("LangFuse 자격증명 설정됨")
            st.caption(f"host: {settings.langfuse_host}")
        else:
            st.warning("LangFuse 키 없음")
            st.caption(
                ".env 에 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 를 설정하세요 "
                "(.env.example 참고)."
            )

    st.info(
        "M0 부트스트랩 화면입니다. 다음 단계(M1 수집)부터 LangFuse 트레이스 조회가 붙습니다."
    )


if __name__ == "__main__":
    main()
