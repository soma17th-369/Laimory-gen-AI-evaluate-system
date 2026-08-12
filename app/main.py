"""Streamlit 진입점 (멀티페이지).

로컬 실행:

    uv run streamlit run app/main.py

`st.navigation` 으로 4개 페이지를 등록한다. 각 페이지 로직은 app/ui/*.py 의 render().
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

from app.ui import dashboard, improvement, task_review, testdata  # noqa: E402

st.set_page_config(
    page_title="Laimory 생성형 AI 평가",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

_PAGES = [
    st.Page(dashboard.render, title="대시보드", icon="📊", url_path="dashboard", default=True),
    st.Page(task_review.render, title="Task 리뷰·채점", icon="🔍", url_path="task-review"),
    st.Page(improvement.render, title="개선책", icon="🛠", url_path="improvement"),
    st.Page(testdata.render, title="테스트 데이터", icon="🧪", url_path="testdata"),
]

st.navigation(_PAGES).run()
