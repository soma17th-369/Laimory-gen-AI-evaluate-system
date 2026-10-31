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
    dev_test,
    evaluation_results,
    improvement,
    improvement_history,
    log_collection,
    pipeline_doc,
    rubric_settings,
    task_review,
    testdata,
)

st.set_page_config(
    page_title="Laimory 생성형 AI 평가",
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
    st.Page(dashboard.render, title="대시보드", url_path="dashboard", default=True),
    st.Page(pipeline_doc.render, title="파이프라인 설명", url_path="pipeline"),
    st.Page(log_collection.render, title="LangFuse 로그 수집", url_path="log-collection"),
    st.Page(task_review.render, title="Task 리뷰·채점", url_path="task-review"),
    st.Page(evaluation_results.render, title="채점 결과", url_path="evaluation-results"),
    st.Page(improvement.render, title="개선책", url_path="improvement"),
    st.Page(
        improvement_history.render,
        title="개선 history",
        url_path="improvement-history",
    ),
    st.Page(testdata.render, title="테스트 데이터", url_path="testdata"),
    st.Page(dev_test.render, title="Dev 환경 테스트", url_path="dev-test"),
    st.Page(rubric_settings.render, title="채점 기준 설정", url_path="rubric-settings"),
]

st.navigation(_PAGES).run()
