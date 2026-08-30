"""④ 테스트 데이터 — 두 기능.

(a) 개선책 기반: 개선책이 실제 반영됐는지 검증할 테스트 케이스(입력+기대) 생성.
(b) 로그 input 기반: 수집된 트레이스의 실제 input 을 추출해 그냥 테스트 실행용 데이터로 저장.
"""

from __future__ import annotations

import streamlit as st

from app import environments
from app.analysis.providers import (
    JudgeProviderError,
    get_llm_provider,
    llm_provider_label,
    llm_setup_error,
)
from app.langfuse_client import get_trace
from app.storage import store
from app.storage.paths import collection_file, improvements_dir, testdata_file
from app.storage.store import list_json, load_json
from app.testdata.generate import testsuite_to_json
from app.testdata.schema import TestSuite

_SYSTEM = (
    "개선책을 검증하기 위한 테스트 케이스(입력 + 기대 조건)를 만든다. 실명·실주소 금지(가상값). "
    "모든 텍스트는 한국어. 지정된 JSON 스키마로만 답한다."
)


def _load_improvements() -> list[dict]:
    out = []
    for path in list_json(improvements_dir()):
        data = load_json(path)
        if isinstance(data, dict):
            out.append(data)
    return out


def _gen_from_improvement(plan_text: str) -> TestSuite:
    user = f"[개선책]\n{plan_text}\n\n이 개선이 실제로 반영됐는지 검증하는 테스트 케이스를 만들어라."
    return get_llm_provider().generate_structured(
        system_prompt=_SYSTEM,
        user_prompt=user,
        result_model=TestSuite,
    )


def _tab_from_improvement() -> None:
    improvements = _load_improvements()
    if not improvements:
        st.info("먼저 **개선책** 페이지에서 개선책을 만드세요.")
        return
    labels = {i.get("slug", "?"): i for i in improvements}
    key = st.selectbox("개선책 선택", options=list(labels.keys()))
    slug = st.text_input("저장 이름", value=f"{key}-verify", key="td_imp_slug")
    setup_error = llm_setup_error()
    if st.button(
        "테스트 케이스 생성",
        type="primary",
        disabled=setup_error is not None,
        key="td_imp_btn",
    ):
        try:
            with st.spinner(f"생성 중… ({llm_provider_label()})"):
                suite = _gen_from_improvement(labels[key].get("plan", ""))
            store.save_json(testdata_file("from-improvement", slug), suite.model_dump())
            st.session_state["td_imp_json"] = testsuite_to_json(suite)
            st.toast(f"저장: testdata/from-improvement/{slug}.json")
        except JudgeProviderError as exc:
            st.error(f"생성 실패 [{exc.code}]: {exc}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"생성 실패: {type(exc).__name__}: {exc}")
    st.caption(f"LLM Provider: {llm_provider_label()}")
    if setup_error:
        st.caption(setup_error)
    if st.session_state.get("td_imp_json"):
        st.download_button(
            "테스트 스위트 .json", data=st.session_state["td_imp_json"], file_name="testsuite.json", mime="application/json"
        )


def _tab_from_logs() -> None:
    st.caption("수집된 트레이스의 실제 input 을 추출해 테스트 실행용 데이터로 저장합니다.")
    rows = store.load_json(collection_file()) or []
    if not rows:
        st.info("먼저 **LangFuse 로그 수집** 페이지에서 로그를 수집하세요.")
        return
    options = {r["id"]: r for r in rows if r.get("id")}
    picked = st.multiselect(
        "input 을 추출할 트레이스",
        options=list(options.keys()),
        format_func=lambda i: (
            f"[{environments.short_label(environments.of(options[i]))}] "
            f"{options[i].get('name')} · {str(i)[:8]}"
        ),
    )
    slug = st.text_input("저장 이름", value="from-logs", key="td_log_slug")
    if st.button("input 추출·저장", type="primary", disabled=not picked, key="td_log_btn"):
        try:
            inputs = []
            with st.spinner("추출 중…"):
                for trace_id in picked:
                    # 상세 조회는 그 트레이스가 있는 프로젝트로 보내야 한다.
                    env = environments.of(options[trace_id])
                    detail = get_trace(trace_id, env)
                    inputs.append(
                        {
                            "traceId": trace_id,
                            "env": env,
                            "input": getattr(detail, "input", None),
                        }
                    )
            store.save_json(testdata_file("from-logs", slug), {"slug": slug, "inputs": inputs})
            st.session_state["td_log_count"] = len(inputs)
            st.toast(f"저장: testdata/from-logs/{slug}.json")
        except Exception as exc:  # noqa: BLE001
            st.error(f"추출 실패: {type(exc).__name__}: {exc}")
    if st.session_state.get("td_log_count"):
        st.success(f"{st.session_state['td_log_count']}건 추출·저장됨")


def render() -> None:
    st.title("🧪 테스트 데이터")
    tab1, tab2 = st.tabs(["개선책 기반 (검증용)", "로그 input 기반 (실행용)"])
    with tab1:
        _tab_from_improvement()
    with tab2:
        _tab_from_logs()
