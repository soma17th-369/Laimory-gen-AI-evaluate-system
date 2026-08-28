"""③ 개선책 — task 별 저장된 평가를 골라 모아 하나의 개선책 생성.

평가기준·지령은 화면에서 편집 후 전송. 결과는 data/improvements/<slug>.json 에 저장.
여러 task 의 문제점을 통합한 하나의 개선책이 된다.

생성한 개선책의 **반영 상태와 반영 시기**도 이 페이지에서 관리한다. 반영 시기를 확정한
개선책만 개선 history 페이지의 전후 비교 대상이 된다(→ [app.improve.records][]).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.analysis.judge import get_openai_client
from app.analysis.schema import CRITERION_LABELS
from app.collect.sync import parse_timestamp
from app.config import get_settings
from app.improve import records
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


def _fmt_time(value: str | None) -> str:
    parsed = parse_timestamp(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M") if parsed else "-"


def _tab_generate() -> None:
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
    if records.load(slug) is not None:
        st.warning(f"같은 이름의 개선책이 이미 있습니다. 생성하면 덮어쓰고 상태는 '미반영'으로 돌아갑니다.")

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
                        "createdAt": records.now_iso(),
                        "status": records.STATUS_DRAFT,  # 반영 여부는 아래 '반영 상태' 에서 관리
                        "appliedAt": None,
                        "note": "",
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


def _status_form(record: dict) -> None:
    """개선책 하나의 상태·반영 시기·메모 편집."""
    slug = record["slug"]
    keys = list(records.STATUS_LABELS.keys())
    applied_at = parse_timestamp(record.get("appliedAt"))
    default = (applied_at or datetime.now().astimezone()).astimezone()

    cols = st.columns([1, 1, 1, 2])
    with cols[0]:
        status = st.selectbox(
            "상태",
            options=keys,
            index=keys.index(record["status"]),
            format_func=lambda key: records.STATUS_LABELS[key],
            key=f"imp_status_{slug}",
        )
    with cols[1]:
        day = st.date_input("반영 날짜", value=default.date(), key=f"imp_date_{slug}")
    with cols[2]:
        clock = st.time_input("반영 시각", value=default.time().replace(microsecond=0), key=f"imp_time_{slug}")
    with cols[3]:
        note = st.text_input("메모(무엇을 반영했는지)", value=record.get("note") or "", key=f"imp_note_{slug}")

    if status != records.STATUS_APPLIED:
        st.caption("'반영됨' 으로 두어야 개선 history 의 전후 비교 대상이 됩니다.")

    if st.button("상태 저장", type="primary", key=f"imp_save_{slug}"):
        stamp = datetime.combine(day, clock).astimezone().isoformat(timespec="seconds")
        try:
            saved = records.save_status(slug, status=status, applied_at=stamp, note=note)
        except Exception as exc:  # noqa: BLE001
            st.error(f"저장 실패: {type(exc).__name__}: {exc}")
            return
        label = records.STATUS_LABELS[saved["status"]]
        when = _fmt_time(saved.get("appliedAt"))
        st.success(f"{slug} → {label}" + (f" · 반영 {when}" if saved.get("appliedAt") else ""))
        st.rerun()


def _tab_status() -> None:
    saved = records.load_all()
    if not saved:
        st.info("아직 저장된 개선책이 없습니다. **개선책 생성** 탭에서 먼저 만드세요.")
        return

    table = [
        {
            "이름": r["slug"],
            "상태": records.STATUS_LABELS[r["status"]],
            "생성": _fmt_time(r.get("createdAt")),
            "반영 시기": _fmt_time(r.get("appliedAt")),
            "대상 task": len(r.get("taskIds") or []),
            "메모": r.get("note") or "",
        }
        for r in saved
    ]
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)

    by_slug = {r["slug"]: r for r in saved}
    slug = st.selectbox("상태를 바꿀 개선책", options=list(by_slug.keys()))
    record = by_slug[slug]
    _status_form(record)

    with st.expander("개선책 본문"):
        st.markdown(record.get("plan") or "(내용 없음)")


def render() -> None:
    st.title("🛠 개선책")
    st.caption("여러 task 의 평가를 모아 하나의 개선책을 만들고, 반영 여부·시기를 관리합니다.")

    generate_tab, status_tab = st.tabs(["개선책 생성", "반영 상태"])
    with generate_tab:
        _tab_generate()
    with status_tab:
        _tab_status()
