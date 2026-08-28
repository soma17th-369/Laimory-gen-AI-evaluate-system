"""② Task 리뷰·채점 — task 별 전체 처리과정을 중복 없는 trace.json 으로 재구성해 보고 저장.

처리과정(steps)·최종 타임라인(result)·프롬프트(generations)를 명세 구조로 보여주고,
`data/tasks/<taskId>/trace.json` 에 저장한다(프롬프트는 §14 권고대로 trace.json 통합).
채점 결과는 `data/evaluations/<taskId>.json`.

목록은 개발·운영 로그를 합쳐 보여준다(→ [app.environments][]). 상세 조회는 **그 행이 온
프로젝트로** 보내야 하므로, 선택한 행의 `env` 를 그대로 따라간다. 채점 결과에도 같은 값을 남겨
어느 프로젝트의 task 를 잰 것인지 나중에 알 수 있게 한다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app import environments
from app.analysis.judge import assemble_evidence, score_trace
from app.analysis.rubric import SYSTEM_PROMPT, build_user_prompt
from app.analysis.schema import CRITERION_KEYS, CRITERION_LABELS, METRIC_KEYS, METRIC_LABELS
from app.config import get_settings
from app.langfuse_client import get_trace
from app.prompts import registry
from app.storage import store
from app.storage.paths import collection_file, evaluation_file, task_trace_file
from app.tasks.trace_builder import build_trace_json

RUBRIC_NAME = "judge-rubric"  # 채점 기준 프롬프트의 레지스트리 이름


def _domain_task_id(trace_detail: Any, trace_id: str) -> str:
    raw = getattr(trace_detail, "input", None)
    if isinstance(raw, dict):
        tid = raw.get("taskId") or (raw.get("request") or {}).get("taskId")
        if tid:
            return str(tid)
    return trace_id


def _task_trace_options(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """공용 로그 스냅샷을 taskId 별로 묶는다."""
    summaries: list[dict[str, Any]] = []
    task_to_trace_ids: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        summary = dict(row)
        trace_id = str(summary["id"])
        task_id = str(summary.get("taskId") or trace_id)
        summaries.append(summary)
        task_to_trace_ids.setdefault(task_id, []).append(trace_id)
    return summaries, task_to_trace_ids


def _render_scorecard(card: Any) -> None:
    st.markdown(f"**종합 {card.overall.score} / 10** — {card.summary}")
    rows = [
        {"기준": CRITERION_LABELS[k], "점수": f"{getattr(card.scores, k).score}/10", "근거": getattr(card.scores, k).reason}
        for k in CRITERION_KEYS
    ]
    rows.append({"기준": CRITERION_LABELS["overall"], "점수": f"{card.overall.score}/10", "근거": card.overall.reason})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    metrics = getattr(card, "metrics", None)
    if metrics is not None:
        with st.expander("정량 Metric 20개", expanded=True):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Metric": METRIC_LABELS[key],
                            "값": getattr(metrics, key).value,
                            "분자": getattr(metrics, key).numerator,
                            "분모": getattr(metrics, key).denominator,
                            "근거": getattr(metrics, key).reason,
                        }
                        for key in METRIC_KEYS
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
    if card.findings:
        st.markdown("**문제점**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"기준": CRITERION_LABELS.get(f.criterion, f.criterion), "심각도": f.severity, "설명": f.description}
                    for f in card.findings
                ]
            ),
            width="stretch",
            hide_index=True,
        )


def _judge_and_save(
    trace_id: str,
    task_id: str,
    detail: Any,
    system_prompt: str,
    env: str,
    note: str = "",
) -> None:
    try:
        # 채점에 쓴 기준을 버전으로 확정(같은 본문이면 기존 버전 재사용).
        version = registry.get_or_create(RUBRIC_NAME, system_prompt, note=note, source="judge")
        trace_json = build_trace_json(detail)
        with st.spinner("채점 중… (OpenAI)"):
            card = score_trace(detail, system_prompt=system_prompt)
        st.session_state.setdefault("tr_cards", {})[trace_id] = card
        # 채점 결과 페이지에서 네트워크 재조회 없이 입출력을 비교할 수 있게 함께 저장한다.
        input_data = {"task": trace_json["task"], "source": trace_json["source"]}
        output_data = trace_json["result"]["timeline"]
        if output_data is None:
            output_data = trace_json["operation"]
        store.save_json(task_trace_file(task_id), trace_json)
        path = evaluation_file(task_id)
        store.save_json(
            path,
            {
                "taskId": task_id,
                "traceId": trace_id,
                "env": env,  # 어느 LangFuse 프로젝트의 task 를 잰 것인지
                "name": getattr(detail, "name", None),
                "rubricRef": {"name": version["name"], "version": version["version"]},  # 채점 기준 버전
                "systemPrompt": system_prompt,  # 재현용 본문(해당 버전과 동일)
                "inputPrompt": build_user_prompt(assemble_evidence(detail)),  # 채점 입력 프롬프트
                "inputData": input_data,
                "outputData": output_data,
                "scorecard": card.model_dump(),  # 결과
            },
        )
        st.session_state["tr_saved_path"] = path.as_posix()
        st.toast(f"평가 저장(기준 v{version['version']}): {path.as_posix()}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"채점 실패: {type(exc).__name__}: {exc}")


def _render_scoring(selected: str, task_id: str, detail: Any, env: str) -> None:
    st.subheader("채점")

    versions = registry.list_versions(RUBRIC_NAME)
    labels = {
        v["version"]: f"v{v['version']} · {v.get('note') or '메모 없음'} · {v.get('createdAt', '')[:16]}"
        for v in versions
    }
    # 불러오기 옵션: 저장된 버전(최신 우선) + 코드 기본값(sentinel 0)
    options = [v["version"] for v in reversed(versions)] + [0]
    picked = st.selectbox(
        "기준 버전 (불러오기)",
        options,
        index=0,
        format_func=lambda v: "코드 기본값 (미저장)" if v == 0 else labels[v],
        key=f"rubric_base_{selected}",
        help="과거 버전을 골라 편집기에 불러옵니다. 편집 후 '새 버전으로 저장'하거나 채점하면 버전이 만들어집니다.",
    )
    base_content = SYSTEM_PROMPT if picked == 0 else (registry.get(RUBRIC_NAME, picked) or {}).get("content", SYSTEM_PROMPT)

    # 선택한 기준 버전이 바뀌면 편집기 내용을 그 버전으로 되돌린다.
    editor_key = f"rubric_editor_{selected}"
    applied_key = f"rubric_applied_{selected}"
    if editor_key not in st.session_state or st.session_state.get(applied_key) != picked:
        st.session_state[editor_key] = base_content
        st.session_state[applied_key] = picked

    system_prompt = st.text_area(
        "채점 기준 (system prompt · 편집 가능)",
        height=280,
        key=editor_key,
        help="편집하면 이 기준으로 채점합니다. 점수 7기준+전반과 v3 Metric 20개는 스키마로 고정됩니다.",
    )
    note = st.text_input("변경 메모 (새 버전 저장·채점 시 기록)", key=f"rubric_note_{selected}")

    save_col, judge_col = st.columns(2)
    if save_col.button("새 버전으로 저장", key=f"rubric_save_{selected}", width="stretch"):
        before = registry.latest(RUBRIC_NAME)
        rec = registry.get_or_create(RUBRIC_NAME, system_prompt, note=note, source="manual")
        if before is None or rec["version"] != before["version"]:
            st.toast(f"새 버전 저장: {RUBRIC_NAME} v{rec['version']}")
        else:
            st.toast(f"변경 없음 — 최신 v{rec['version']} 그대로")

    can_judge = get_settings().has_openai_credentials()
    if judge_col.button("이 task 채점", type="primary", disabled=not can_judge, key=f"judge_{selected}", width="stretch"):
        _judge_and_save(selected, task_id, detail, system_prompt, env, note=note)
    if not can_judge:
        st.caption("채점하려면 .env 에 OPENAI_API_KEY 설정이 필요합니다.")

    with st.expander("채점 입력 프롬프트 (judge 에 들어가는 근거)"):
        st.code(build_user_prompt(assemble_evidence(detail)))

    with st.expander(f"채점 기준 버전 이력 ({len(versions)}개)"):
        if not versions:
            st.caption("저장된 버전이 아직 없습니다. 편집 후 저장하거나 채점하면 v1 이 생성됩니다.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "버전": f"v{v['version']}",
                            "생성": v.get("createdAt", "")[:16],
                            "출처": v.get("source"),
                            "부모": f"v{v['parent']}" if v.get("parent") else "-",
                            "메모": v.get("note") or "-",
                        }
                        for v in reversed(versions)
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

    saved_path = st.session_state.get("tr_saved_path")
    if saved_path:
        st.caption(f"저장 위치: `{saved_path}` (기준 버전·입력 프롬프트·결과 포함)")

    card = st.session_state.get("tr_cards", {}).get(selected)
    if card is not None:
        _render_scorecard(card)


def _render_process(tj: dict) -> None:
    steps = tj["process"]["steps"]
    generations = tj["process"]["generations"]

    with st.expander(f"처리 과정 (steps {len(steps)}개, 실행 순서)", expanded=True):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "순서": s["order"],
                        "단계": s["name"],
                        "유형": s["type"],
                        "입력참조": ", ".join(s["inputRefs"]),
                        "GEN": len(s["generationRefs"]),
                    }
                    for s in steps
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    with st.expander("최종 타임라인 (result.timeline)"):
        st.json(tj["result"]["timeline"] or {}, expanded=False)

    with st.expander(f"프롬프트 (generations {len(generations)}개)"):
        if not generations:
            st.caption("이 트레이스에는 GENERATION 관측치가 없습니다.")
        for gen in generations:
            st.markdown(f"**{gen['name']}** · `{gen['model']}`")
            for msg in gen.get("input") or []:
                if isinstance(msg, dict):
                    st.caption(f"<{msg.get('role')}>")
                    st.code(str(msg.get("content", ""))[:4000])


def render() -> None:
    st.title("🔍 Task 리뷰·채점")
    st.caption(
        "LangFuse 로그 수집 페이지에서 만든 공용 로그(개발·운영 합계)를 taskId별로 검토하고 채점합니다."
    )

    traces = store.load_json(collection_file()) or []
    if not traces:
        st.info("먼저 **LangFuse 로그 수집** 페이지에서 로그를 수집하세요.")
        return

    summaries, task_to_trace_ids = _task_trace_options(traces)
    if not summaries:
        st.warning("공용 로그에 사용할 수 있는 트레이스가 없습니다. 다시 수집하세요.")
        return
    id_to_summary = {s["id"]: s for s in summaries}
    st.dataframe(pd.DataFrame(summaries), width="stretch", hide_index=True)

    selected_task_id = st.selectbox(
        "채점할 taskId",
        options=list(task_to_trace_ids.keys()),
        format_func=lambda task_id: f"{task_id} · 트레이스 {len(task_to_trace_ids[task_id])}개",
        help="Langfuse 트레이스 입력의 taskId를 기준으로 묶은 목록입니다.",
    )
    trace_options = task_to_trace_ids[selected_task_id]
    if len(trace_options) == 1:
        selected = trace_options[0]
        st.caption(
            f"트레이스: {id_to_summary[selected].get('name') or '(이름없음)'} · "
            f"`{selected}` · {environments.label(environments.of(id_to_summary[selected]))}"
        )
    else:
        selected = st.selectbox(
            "해당 task의 트레이스",
            options=trace_options,
            format_func=lambda trace_id: (
                f"[{environments.short_label(environments.of(id_to_summary[trace_id]))}] "
                f"{id_to_summary[trace_id].get('name') or '(이름없음)'} · {trace_id[:8]}"
            ),
            help="하나의 taskId에 여러 Langfuse 트레이스가 있으면 채점할 트레이스를 선택하세요.",
        )
    if not selected:
        return

    # 상세 조회는 그 트레이스가 있는 프로젝트로 보내야 한다.
    env = environments.of(id_to_summary[selected])

    detail_cache = st.session_state.setdefault("tr_detail", {})
    if selected not in detail_cache:
        try:
            with st.spinner(f"상세 조회 중… ({environments.label(env)})"):
                detail_cache[selected] = get_trace(selected, env)
        except Exception as exc:  # noqa: BLE001
            st.error(f"상세 조회 실패: {type(exc).__name__}: {exc}")
            return
    detail = detail_cache[selected]
    task_id = _domain_task_id(detail, selected)

    tj_cache = st.session_state.setdefault("tr_tracejson", {})
    if selected not in tj_cache:
        tj_cache[selected] = build_trace_json(detail)
    tj = tj_cache[selected]

    st.divider()
    st.markdown(
        f"### {getattr(detail, 'name', None) or '(이름없음)'}  ·  task `{task_id}`  ·  "
        f"{environments.label(env)}"
    )
    cols = st.columns(4)
    cols[0].metric("관측치", tj["langfuse"]["observationCount"])
    cols[1].metric("처리 단계", len(tj["process"]["steps"]))
    cols[2].metric("LLM 호출", len(tj["process"]["generations"]))
    cols[3].metric("최종 event", len((tj["result"]["timeline"] or {}).get("events") or []))

    if st.button("처리과정 저장 (trace.json)", key=f"save_{selected}"):
        store.save_json(task_trace_file(task_id), tj)
        st.toast(f"저장: tasks/{task_id}/trace.json")

    _render_process(tj)

    _render_scoring(selected, task_id, detail, env)
