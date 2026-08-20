"""Streamlit 진입점 (멀티페이지).

로컬 실행:

    uv run streamlit run app/main.py

`st.navigation` 으로 페이지를 등록한다. 각 페이지 로직은 app/ui/*.py 의 render().
`streamlit run app/main.py` 는 app/ 를 sys.path 에 넣으므로 프로젝트 루트를 추가해 패키지
import(app.ui …)가 되게 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app.ui import (  # noqa: E402
    dashboard,
    evaluation_results,
    improvement,
    improvement_history,
    log_collection,
    task_review,
    testdata,
)

st.set_page_config(
    page_title="Laimory 생성형 AI 평가",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 기본 sidebar header가 60px 높이와 16px 아래 여백을 차지해 내비게이션이 불필요하게
# 내려간다. 접기 버튼 공간은 유지하면서 메뉴만 위로 당긴다.
st.markdown(
    """
    <style>
    [data-testid="stSidebarHeader"] {
        height: 44px;
        margin-bottom: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

_PAGES = [
    st.Page(dashboard.render, title="대시보드", icon="📊", url_path="dashboard", default=True),
    st.Page(log_collection.render, title="LangFuse 로그 수집", icon="📥", url_path="log-collection"),
    st.Page(task_review.render, title="Task 리뷰·채점", icon="🔍", url_path="task-review"),
    st.Page(evaluation_results.render, title="채점 결과", icon="📋", url_path="evaluation-results"),
    st.Page(improvement.render, title="개선책", icon="🛠", url_path="improvement"),
    st.Page(
        improvement_history.render,
        title="개선 history",
        icon="📈",
        url_path="improvement-history",
    ),
    st.Page(testdata.render, title="테스트 데이터", icon="🧪", url_path="testdata"),
]

st.navigation(_PAGES).run()
