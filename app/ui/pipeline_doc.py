"""파이프라인 설명 — 대상 AI 서버(Laimory-AI)의 Timeline·User Memory 처리 과정.

평가 대상이 무엇을 어떤 순서로 하는지 모르면 로그를 읽어도 어느 단계가 잘못됐는지 짚을 수
없다. 그래서 Laimory-AI 저장소에서 만든 설명 문서(단일 HTML, 프롬프트 원문 포함)를
`assets/docs/laimory-pipeline.html` 에 그대로 두고 이 앱 안에 띄운다.

문서 자체는 손대지 않고 iframe 에 넣는다 — 문서의 CSS·목차·복사 버튼이 앱과 섞이지 않는다.
앱 안에서만 필요한 표시 규칙(목차 폭·목차 링크)은 렌더링 때 끼우고(→ `prepare_for_iframe`),
테마는 Streamlit 설정을 따라 넘긴다(→ `with_theme`). 문서를 새로 받으면 파일만 덮어쓴다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = _PROJECT_ROOT / "assets" / "docs" / "laimory-pipeline.html"
"""설명 문서. Laimory-AI 저장소에서 생성한 HTML 을 그대로 둔다."""

_HTML_TAG = re.compile(r"<html\b[^>]*>")

_EMBED_CSS = """<style>
/* 앱 안에서는 문서가 본문 폭(사이드바 제외)만 쓴다. 문서 자체 규칙(1080px)보다 일찍 목차를 편다. */
@media (min-width: 940px) {
  .layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 40px; align-items: start; }
  .rail { display: block; position: sticky; top: 24px; padding-top: 4px; }
  .rail ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }
  .rail a { display: block; padding: 5px 0 5px 12px; border-left: 2px solid var(--rule);
            color: var(--muted); text-decoration: none; font-size: 13px; line-height: 1.45; }
  .rail a:hover, .rail a:focus-visible { color: var(--ink); border-left-color: var(--code); }
  .rail .rail-top { font-family: "Noto Serif KR", serif; color: var(--ink); font-size: 14px; margin-top: 18px; }
  .rail .rail-top:first-child { margin-top: 0; }
}
.masthead { padding-top: 40px; }
</style>
</head>"""
"""iframe 안에서만 덧붙이는 표시 규칙. 저장된 문서는 건드리지 않는다.

문서의 왼쪽 목차(rail)는 문서 폭 1080px 부터 펴진다. 앱 안에서는 사이드바를 뺀 본문 폭이
그 문서 폭이라 1536px 화면(노트북 125% 배율)에서도 목차가 접힌다. 목차 규칙을 940px 부터
한 번 더 선언해 앱 안에서는 일찍 펴지게 한다. 규칙 본문은 문서의 것을 그대로 옮긴 것이다.
"""

_EMBED_SCRIPT = """<script>
// srcdoc 문서의 기준 URL 은 앱 페이지라, 목차의 "#id" 링크를 그대로 두면 iframe 안에 앱이 다시
// 열린다. 이 문서의 스크롤만 옮긴다. scrollIntoView 는 바깥 앱 화면까지 끌어올리므로 쓰지 않는다.
document.addEventListener('click', function (event) {
  var link = event.target.closest('a[href^="#"]');
  if (!link) return;
  var target = document.getElementById(link.getAttribute('href').slice(1));
  if (!target) return;
  event.preventDefault();
  var scroller = document.scrollingElement || document.documentElement;
  scroller.scrollTo({ top: target.getBoundingClientRect().top + scroller.scrollTop - 24 });
});
</script>
</body>"""
"""iframe 안에서만 덧붙이는 스크립트. 문서의 목차 링크가 iframe 밖으로 새지 않게 한다."""

_FRAME_HEIGHT = 1400
"""iframe 기본 높이(px). 실제 높이는 아래 CSS 가 화면에 맞춰 늘린다.

`height="content"` 로 문서 전체를 펼치지 않는 이유: 문서의 왼쪽 목차(rail)는 문서 자신의
스크롤에 붙어 있다. 문서를 통째로 펼치면 목차가 첫 화면과 함께 위로 사라진다. 화면 높이만큼의
창 안에서 문서가 스크롤돼야 목차가 따라온다.
"""

_FRAME_CSS = """
<style>
[data-testid="stIFrame"] {
    height: calc(100vh - 230px) !important;
    min-height: 640px;
}
</style>
"""
"""문서를 화면 높이만큼 보여준다. 문서 안에 자체 목차(왼쪽 rail)가 있어 안쪽 스크롤이 자연스럽다."""

LANGFUSE_NAMES: list[dict[str, str]] = [
    {"LangFuse 이름": "generate-timeline", "종류": "트레이스", "문서의 단계": "Timeline · 실행 흐름 9단계", "메모": "POST /v1/timeline 한 번 = 트레이스 하나. 아래 GENERATION 이 이 안에 들어 있다"},
    {"LangFuse 이름": "infer-location-events", "종류": "GENERATION", "문서의 단계": "Location Event Agent", "메모": "run_event_agents (병렬 5개 중 하나)"},
    {"LangFuse 이름": "infer-calendar-events", "종류": "GENERATION", "문서의 단계": "Calendar Event Agent", "메모": "run_event_agents"},
    {"LangFuse 이름": "describe-photo-images", "종류": "GENERATION", "문서의 단계": "Photo Describer", "메모": "Photo Agent 의 describe 노드(이미지 첨부 → 메타데이터 순)"},
    {"LangFuse 이름": "infer-photo-events", "종류": "GENERATION", "문서의 단계": "Photo Event Agent", "메모": "run_event_agents"},
    {"LangFuse 이름": "infer-sleep-activity-events", "종류": "GENERATION", "문서의 단계": "Sleep/Activity Event Agent", "메모": "run_event_agents"},
    {"LangFuse 이름": "infer-notification-events", "종류": "GENERATION", "문서의 단계": "Notification Event Agent", "메모": "run_event_agents. 입력이 가장 큰 호출"},
    {"LangFuse 이름": "generate-timeline-draft", "종류": "GENERATION", "문서의 단계": "Timeline Agent", "메모": "run_timeline_agent. Repair 가 rerun_timeline_agent 를 부르면 다시 나온다"},
    {"LangFuse 이름": "analyze-timeline-repair", "종류": "GENERATION", "문서의 단계": "Repair Agent (analyze)", "메모": "run_repair_agent 의 analyze → execute → confirm 반복. 최대 3회"},
    {"LangFuse 이름": "generate-event-questions", "종류": "GENERATION", "문서의 단계": "Question Agent", "메모": "run_question_agent. Repair 뒤에만"},
    {"LangFuse 이름": "update-user-memory", "종류": "트레이스", "문서의 단계": "User Memory · 실행 흐름 5단계", "메모": "POST /v1/user-memory 한 번 = 트레이스 하나"},
    {"LangFuse 이름": "update-user-memory-profile", "종류": "GENERATION", "문서의 단계": "User Memory Agent", "메모": "갱신 Agent. 위반 재요청까지 최대 3회"},
]
"""LangFuse 에 실제로 남는 이름 ↔ 문서의 단계. 이름이 곧 대응이라 표로만 잇는다."""


def with_theme(html: str, theme: str | None) -> str:
    """Streamlit 테마를 문서의 `<html data-theme>` 로 넘긴다. 모르는 값이면 문서 기본(OS 설정)."""
    if theme not in ("light", "dark"):
        return html
    return _HTML_TAG.sub(f'<html lang="ko" data-theme="{theme}">', html, count=1)


def prepare_for_iframe(html: str) -> str:
    """iframe 표시용 규칙을 `</head>` 앞에, 목차 스크립트를 `</body>` 앞에 한 번씩 끼운다.

    닫는 태그가 없으면 그 자리는 그대로 둔다. 저장된 문서 파일은 바뀌지 않는다.
    """
    return html.replace("</head>", _EMBED_CSS, 1).replace("</body>", _EMBED_SCRIPT, 1)


def _streamlit_theme() -> str | None:
    """현재 세션의 테마 종류. 세션 밖(테스트 등)에서는 None."""
    try:
        theme: Any = st.context.theme
        return str(theme.type) if theme is not None and theme.type else None
    except Exception:  # noqa: BLE001 — 테마를 못 읽어도 문서는 보여야 한다
        return None


def render() -> None:
    st.title("파이프라인 설명")
    st.caption(
        "평가 대상인 Laimory-AI 서버가 Timeline 과 User Memory 를 만드는 과정. "
        "어느 단계가 LLM 이고 어느 단계가 코드인지, 각 단계가 무엇을 확정하는지를 적은 문서다."
    )

    with st.expander("LangFuse 이름 ↔ 문서의 단계", expanded=False):
        st.caption(
            "로그에 남는 트레이스·GENERATION 이름이 문서의 어느 단계인지. "
            "Task 리뷰에서 본 이름을 여기서 찾아 문서로 넘어간다."
        )
        st.dataframe(LANGFUSE_NAMES, width="stretch", hide_index=True)

    if not DOCUMENT.is_file():
        st.error(f"설명 문서가 없습니다: `{DOCUMENT.relative_to(_PROJECT_ROOT)}`")
        return

    html = DOCUMENT.read_text(encoding="utf-8")
    st.markdown(_FRAME_CSS, unsafe_allow_html=True)
    st.iframe(prepare_for_iframe(with_theme(html, _streamlit_theme())), height=_FRAME_HEIGHT)
