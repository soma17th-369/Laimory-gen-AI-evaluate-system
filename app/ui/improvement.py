"""③ 개선책 — task 별 저장된 평가를 골라 모아 하나의 개선책 생성.

평가기준·지령은 화면에서 편집 후 전송. 결과는 data/improvements/<slug>.json 에 저장.
여러 task 의 문제점을 통합한 하나의 개선책이 된다.
"""

from __future__ import annotations

import streamlit as st

from app.analysis.judge import get_openai_client
from app.analysis.schema import CRITERION_LABELS
from app.config import get_settings
from app.storage import store
from app.storage.paths import evaluations_dir, improvement_file
from app.storage.store import list_json, load_json

_DEFAULT_INSTRUCTION = """다음은 여러 task 의 채점 문제점 모음이다. 공통·반복되는 문제를 묶고 우선순위를 매겨,
파이프라인(프롬프트·후처리)을 어떻게 고칠지 실행 가능한 '개선책'을 한국어로 작성하라.
- 여러 task 에 걸쳐 반복되는 문제를 먼저 다룬다.
- 각 개선 항목: 문제 → 원인 추정 → 구체적 조치.
- 근거(문제점)에 없는 추측은 하지 않는다."""


def _load_evaluations() -> list[dict]:
    out = []
    for path in list_json(evaluations_dir()):
        data = load_json(path)
        if isinstance(data, dict):
            out.append(data)
    return out


def _findings_block(evaluations: list[dict]) -> str:
    lines = []
    for ev in evaluations:
        sc = ev.get("scorecard", {})
        overall = (sc.get("overall") or {}).get("score")
        lines.append(f"## task {ev.get('taskId')} (종합 {overall}/10)")
        for f in sc.get("findings", []) or []:
            label = CRITERION_LABELS.get(f.get("criterion"), f.get("criterion"))
            lines.append(f"- [{f.get('severity')}] ({label}) {f.get('description')}")
    return "\n".join(lines)


def _generate(evaluations: list[dict], instruction: str) -> str:
    client = get_openai_client()
    model = get_settings().openai_judge_model
    user = f"{instruction}\n\n[문제점 모음]\n{_findings_block(evaluations)}"

    def call(**extra):
        return client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": user}], **extra
        )

    try:
        resp = call(temperature=0)
    except Exception as exc:  # noqa: BLE001
        if "temperature" in str(exc).lower():
            resp = call()
        else:
            raise
    return resp.choices[0].message.content or ""


def render() -> None:
    st.title("🛠 개선책")
    st.caption("여러 task 의 평가를 모아 하나의 개선책 생성")

    evaluations = _load_evaluations()
    if not evaluations:
        st.info("먼저 **Task 리뷰·채점**에서 채점하면 평가가 여기에 쌓입니다.")
        return

    labels = {
        f"{e.get('taskId')} · {e.get('name')} (종합 {(e.get('scorecard') or {}).get('overall', {}).get('score')}/10)": e
        for e in evaluations
    }
    picked = st.multiselect("포함할 task 평가", options=list(labels.keys()), default=list(labels.keys()))
    instruction = st.text_area("평가기준·지령 (편집 후 전송)", value=_DEFAULT_INSTRUCTION, height=200)
    slug = st.text_input("저장 이름(slug)", value="improvement")

    if st.button("개선책 생성", type="primary", disabled=not get_settings().has_openai_credentials()):
        selected = [labels[k] for k in picked]
        if not selected:
            st.warning("task 를 하나 이상 선택하세요.")
        else:
            try:
                with st.spinner("개선책 생성 중… (OpenAI)"):
                    text = _generate(selected, instruction)
                store.save_json(
                    improvement_file(slug),
                    {
                        "slug": slug,
                        "taskIds": [e.get("taskId") for e in selected],
                        "instruction": instruction,
                        "plan": text,
                    },
                )
                st.session_state["improvement_text"] = text
                st.toast(f"저장: improvements/{slug}.json")
            except Exception as exc:  # noqa: BLE001
                st.error(f"생성 실패: {type(exc).__name__}: {exc}")

    text = st.session_state.get("improvement_text")
    if text:
        st.markdown("### 개선책")
        st.markdown(text)
        st.download_button("개선책 .md 다운로드", data=text, file_name="improvement.md", mime="text/markdown")
