"""Streamlit 진입점.

로컬 실행:

    uv run streamlit run app/main.py

`streamlit run app/main.py` 는 이 파일이 있는 디렉터리(app/)를 sys.path 에 넣으므로,
패키지 경로(`app.config`)로 import 하려면 프로젝트 루트를 경로에 추가한다.
"""

from __future__ import annotations

import sys
from datetime import datetime, time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.analysis.judge import OpenAINotConfigured, score_trace  # noqa: E402
from app.analysis.schema import CRITERION_KEYS, CRITERION_LABELS  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.improve.suggest import suggest_prompt_improvements  # noqa: E402
from app.report.build import build_report  # noqa: E402
from app.testdata.generate import generate_test_cases, testsuite_to_json  # noqa: E402
from app.report.export import report_to_json, report_to_markdown  # noqa: E402
from app.report.schema import ReportItem  # noqa: E402
from app.langfuse_client import (  # noqa: E402
    LangfuseNotConfigured,
    get_trace,
    list_traces,
    observation_row,
    trace_summary,
)


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _trace_label(summary: dict) -> str:
    ts = summary.get("timestamp")
    ts_str = ts.strftime("%Y-%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)
    return f"{ts_str} · {summary.get('name') or '(이름없음)'} · {str(summary.get('id'))[:8]}"


def _render_value(label: str, value: object) -> None:
    st.markdown(f"**{label}**")
    if value is None or value == "":
        st.caption("(없음)")
    elif isinstance(value, (dict, list)):
        st.json(value, expanded=False)
    else:
        st.code(str(value))


def _sidebar(configured: bool) -> dict:
    with st.sidebar:
        st.header("LangFuse")
        settings = get_settings()
        if configured:
            st.success("자격증명 설정됨")
            st.caption(f"host: {settings.langfuse_host}")
        else:
            st.warning("키 없음 — .env 설정 필요")

        st.divider()
        st.subheader("조회 필터")
        limit = st.number_input("개수(limit)", min_value=1, max_value=100, value=25)
        name = st.text_input("이름(name)", value="")
        user_id = st.text_input("user_id", value="")

        from_dt = to_dt = None
        if st.checkbox("기간 필터"):
            col1, col2 = st.columns(2)
            d_from = col1.date_input("from", value=None)
            d_to = col2.date_input("to", value=None)
            if d_from:
                from_dt = datetime.combine(d_from, time.min)
            if d_to:
                to_dt = datetime.combine(d_to, time.max)

        fetch = st.button(
            "트레이스 조회",
            type="primary",
            use_container_width=True,
            disabled=not configured,
        )

    return {
        "limit": int(limit),
        "name": name,
        "user_id": user_id,
        "from_dt": from_dt,
        "to_dt": to_dt,
        "fetch": fetch,
    }


def _do_fetch(filters: dict) -> None:
    try:
        with st.spinner("트레이스 조회 중…"):
            resp = list_traces(
                limit=filters["limit"],
                name=filters["name"],
                user_id=filters["user_id"],
                from_timestamp=filters["from_dt"],
                to_timestamp=filters["to_dt"],
            )
        st.session_state["traces"] = list(getattr(resp, "data", []) or [])
        st.session_state["detail_cache"] = {}
    except LangfuseNotConfigured as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001 - UI 에 실패를 그대로 보여준다
        st.error(f"조회 실패: {type(exc).__name__}: {exc}")


def _render_scorecard(card) -> None:
    st.markdown(f"**종합 {card.overall.score} / 10** — {card.summary}")
    rows = []
    for key in CRITERION_KEYS:
        item = getattr(card.scores, key)
        rows.append({"기준": CRITERION_LABELS[key], "점수": f"{item.score}/10", "근거": item.reason})
    rows.append(
        {"기준": CRITERION_LABELS["overall"], "점수": f"{card.overall.score}/10", "근거": card.overall.reason}
    )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if card.findings:
        st.markdown("**문제점**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "기준": CRITERION_LABELS.get(f.criterion, f.criterion),
                        "심각도": f.severity,
                        "설명": f.description,
                    }
                    for f in card.findings
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("문제점 없음")


def _render_judge_section(trace_id: str, detail: object) -> None:
    st.markdown("#### 채점")
    judge_enabled = get_settings().has_openai_credentials()
    bcol, scol = st.columns([1, 3])
    if bcol.button("이 트레이스 채점", disabled=not judge_enabled, key=f"judge_{trace_id}"):
        try:
            with st.spinner("채점 중… (OpenAI)"):
                st.session_state.setdefault("scorecards", {})[trace_id] = score_trace(detail)
        except OpenAINotConfigured as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001 - UI 에 실패를 그대로 보여준다
            st.error(f"채점 실패: {type(exc).__name__}: {exc}")
    if not judge_enabled:
        scol.caption("채점하려면 `.env` 에 OPENAI_API_KEY 설정이 필요합니다.")

    card = st.session_state.get("scorecards", {}).get(trace_id)
    if card is not None:
        _render_scorecard(card)
        _render_prompt_review(trace_id, detail, card)
        _render_testcase_section(trace_id, card)


def _render_prompt_review(trace_id: str, detail: object, card: object) -> None:
    st.markdown("##### 프롬프트 개선 제안")
    if st.button("프롬프트 개선 제안 생성", key=f"review_{trace_id}"):
        try:
            with st.spinner("프롬프트 분석 중… (OpenAI)"):
                review = suggest_prompt_improvements(detail, card)
            st.session_state.setdefault("reviews", {})[trace_id] = review
        except Exception as exc:  # noqa: BLE001
            st.error(f"제안 실패: {type(exc).__name__}: {exc}")

    review = st.session_state.get("reviews", {}).get(trace_id)
    if review is None:
        return
    st.caption(review.summary)
    if not review.suggestions:
        st.caption("제안 없음")
        return
    rows = [
        {
            "단계": s.target_step,
            "기준": ", ".join(CRITERION_LABELS.get(c, c) for c in s.related_criteria),
            "문제": s.problem,
            "수정안": s.suggestion,
        }
        for s in review.suggestions
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_testcase_section(trace_id: str, card: object) -> None:
    st.markdown("##### 테스트 케이스 생성")
    if st.button("테스트 케이스 생성", key=f"testcase_{trace_id}"):
        try:
            with st.spinner("테스트 케이스 생성 중… (OpenAI)"):
                suite = generate_test_cases(card)
            st.session_state.setdefault("testsuites", {})[trace_id] = suite
        except Exception as exc:  # noqa: BLE001
            st.error(f"생성 실패: {type(exc).__name__}: {exc}")

    suite = st.session_state.get("testsuites", {}).get(trace_id)
    if suite is None:
        return
    st.caption(suite.summary)
    for idx, case in enumerate(suite.cases, 1):
        crit = ", ".join(CRITERION_LABELS.get(c, c) for c in case.targets_criteria)
        with st.expander(f"{idx}. {case.title}  ·  {crit}"):
            st.write(case.description)
            st.markdown("**기대 조건**")
            for cond in case.expected:
                st.markdown(f"- {cond}")
            st.markdown("**입력(input)**")
            st.json(case.input.model_dump(), expanded=False)
    st.download_button(
        "테스트 스위트 .json 다운로드",
        data=testsuite_to_json(suite),
        file_name="test-suite.json",
        mime="application/json",
        use_container_width=True,
    )


def _render_detail(trace_id: str) -> None:
    cache: dict = st.session_state.setdefault("detail_cache", {})
    if trace_id not in cache:
        try:
            with st.spinner("상세 조회 중…"):
                cache[trace_id] = get_trace(trace_id)
        except Exception as exc:  # noqa: BLE001
            st.error(f"상세 조회 실패: {type(exc).__name__}: {exc}")
            return
    detail = cache[trace_id]

    st.markdown(f"### {getattr(detail, 'name', None) or '(이름없음)'}")
    observations = list(getattr(detail, "observations", []) or [])
    cols = st.columns(4)
    cols[0].metric("latency(s)", _fmt(getattr(detail, "latency", None)))
    cols[1].metric("cost", _fmt(getattr(detail, "total_cost", None)))
    cols[2].metric("관측치", len(observations))
    cols[3].metric("user", getattr(detail, "user_id", None) or "-")

    st.divider()
    _render_judge_section(trace_id, detail)
    st.divider()

    left, right = st.columns(2)
    with left:
        _render_value("trace input", getattr(detail, "input", None))
    with right:
        _render_value("trace output", getattr(detail, "output", None))

    st.markdown("#### 관측치 (generation / span / event)")
    if not observations:
        st.caption("관측치가 없습니다.")
        return
    st.dataframe(
        pd.DataFrame([observation_row(o) for o in observations]),
        use_container_width=True,
        hide_index=True,
    )
    for obs in observations:
        row = observation_row(obs)
        header = f"[{row['type']}] {row['name'] or ''} · {row['model'] or ''}".strip(" ·")
        with st.expander(header):
            oc1, oc2 = st.columns(2)
            with oc1:
                _render_value("input", getattr(obs, "input", None))
            with oc2:
                _render_value("output", getattr(obs, "output", None))


def _render_report_section() -> None:
    cards: dict = st.session_state.get("scorecards", {})
    if not cards:
        return

    st.divider()
    st.header("채점 리포트")

    id_to_summary = {s["id"]: s for s in (trace_summary(t) for t in st.session_state.get("traces", []) or [])}
    items = []
    for trace_id, card in cards.items():
        summary = id_to_summary.get(trace_id, {})
        ts = summary.get("timestamp")
        items.append(
            ReportItem(
                trace_id=trace_id,
                name=summary.get("name"),
                timestamp=str(ts) if ts is not None else None,
                scorecard=card,
            )
        )

    report = build_report(items, judge_model=get_settings().openai_judge_model)
    su = report.summary
    st.caption(f"채점한 트레이스 {su.trace_count}건 · 평균 전반 {su.avg_overall}/10 · judge `{report.judge_model}`")

    rows = [{"기준": CRITERION_LABELS[k], "평균": f"{su.avg_by_criterion.get(k)}/10"} for k in CRITERION_KEYS]
    rows.append({"기준": CRITERION_LABELS["overall"], "평균": f"{su.avg_overall}/10"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    col1.download_button(
        "리포트 .md 다운로드",
        data=report_to_markdown(report),
        file_name="scorecard-report.md",
        mime="text/markdown",
        use_container_width=True,
    )
    col2.download_button(
        "리포트 .json 다운로드",
        data=report_to_json(report),
        file_name="scorecard-report.json",
        mime="application/json",
        use_container_width=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Laimory 생성형 AI 평가",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("Laimory 생성형 AI 평가 도구")
    st.caption("LangFuse 로그 분석 · 점수 · 문제점 · 프롬프트 개선 · 테스트 데이터 생성")

    configured = get_settings().has_langfuse_credentials()
    filters = _sidebar(configured)

    if not configured:
        st.info(
            "시작하려면 `.env` 에 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 를 설정하고 "
            "다시 실행하세요(.env.example 참고)."
        )
        return

    if filters["fetch"]:
        _do_fetch(filters)

    traces = st.session_state.get("traces")
    if not traces:
        st.info("사이드바에서 **트레이스 조회**를 눌러 LangFuse 로그를 불러오세요.")
        return

    st.subheader(f"트레이스 {len(traces)}건")
    summaries = [trace_summary(t) for t in traces]
    st.dataframe(pd.DataFrame(summaries), use_container_width=True, hide_index=True)

    id_to_summary = {s["id"]: s for s in summaries}
    selected_id = st.selectbox(
        "상세 볼 트레이스",
        options=list(id_to_summary.keys()),
        format_func=lambda i: _trace_label(id_to_summary[i]),
    )
    if selected_id:
        st.divider()
        _render_detail(selected_id)

    _render_report_section()


if __name__ == "__main__":
    main()
