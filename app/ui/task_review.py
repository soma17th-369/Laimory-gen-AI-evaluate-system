"""② Task 리뷰·채점 — 한 Task 의 처리 과정을 보고 **단계별로** 채점한다.

한 화면에서 셋을 같이 본다(→ [app.ui.stage_view][]).

1. 원본 데이터의 상태 — 이 Task 가 무엇을 받았는지.
2. 그 채점이 정확히 무엇을 봤는지 — 단계별 근거(채점 프롬프트에 들어간 그대로).
3. 채점 결과 — 항목별 점수와 이유, 감점 근거, 별도 알림.

목록은 개발·운영 로그를 합쳐 보여주고, 환경 필터(→ [app.ui.env_filter][])로 한 환경만 남길 수
있다(→ [app.environments][]). 상세 조회는 **그 행이 온 프로젝트로** 보내야 하므로 선택한 행의
`env` 를 그대로 따라간다.

기본은 채점 대상만 보여주고, 필요하면 필터를 끈다(→ [app.tasks.review][]).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app import environments
from app.analysis import evaluation_record, evidence as evidence_mod, stages
from app.analysis.providers import JudgeProviderError, llm_provider_label, llm_setup_error
from app.langfuse_client import get_trace
from app.storage import store
from app.storage.paths import collection_file
from app.tasks import review
from app.tasks.trace_builder import build_trace_json
from app.ui import env_filter, stage_view

_COLUMN_ORDER = (
    "env",
    "timestamp",
    "taskId",
    "task",
    "task_time",
    "total_cost",
    "채점 여부",
    "채점 시각",
)
"""표에 보일 열. 이 목록에 없는 값(trace id·user_id 등)은 화면에 내보내지 않는다."""

_TABLE_HEIGHT = 320
"""목록 높이(px). 선택한 행의 상세가 화면 안에서 바로 이어지도록 목록을 짧게 잡는다."""

def _scored_columns(row: dict[str, Any], scored: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """행 하나의 채점 여부. 단계까지는 아래 단계 표에서 보므로 목록에서는 O/X 로만 구분한다.

    구버전(7기준) 결과는 지금 채점과 이어지지 않으므로 `X` 로 둔다.
    """
    record = scored.get(str(row.get("taskId") or ""))
    if record is None or evaluation_record.is_legacy(record):
        return {"채점 여부": "X", "채점 시각": ""}
    if not (record.get("composite") or {}).get("evaluatedCount"):
        return {"채점 여부": "X", "채점 시각": ""}
    return {"채점 여부": "O", "채점 시각": (record.get("updatedAt") or "")[:16].replace("T", " ")}


def display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """표에 그릴 값만 남기고 단위를 붙인다. 순서는 넘긴 그대로(선택 index 가 맞아야 한다)."""
    out = []
    for row in rows:
        latency = row.get("latency")
        cost = row.get("total_cost")
        out.append(
            {
                "env": environments.short_label(environments.of(row)),
                "timestamp": str(row.get("timestamp") or "")[:19],
                "taskId": row.get("taskId"),
                "task": row.get("name"),
                "task_time": f"{latency:.1f}s" if isinstance(latency, (int, float)) else "",
                "total_cost": f"${cost:.4f}" if isinstance(cost, (int, float)) else "",
                "채점 여부": row.get("채점 여부", "X"),
                "채점 시각": row.get("채점 시각", ""),
            }
        )
    return out


def _selectable_rows(
    rows: list[dict[str, Any]],
    *,
    only_scorable: bool,
    scored: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """표에 그대로 넘길 행 목록. 선택은 이 리스트의 위치로 돌아온다."""
    usable = [dict(row) for row in rows if isinstance(row, dict) and row.get("id")]
    if only_scorable:
        usable = [row for row in usable if review.is_scorable(row)]
    if scored is not None:
        for row in usable:
            row.update(_scored_columns(row, scored))
    return usable


def _picked_row(rows: list[dict[str, Any]], selection: Any) -> dict[str, Any] | None:
    positions = list(getattr(selection, "rows", None) or [])
    if not positions:
        return None
    index = int(positions[0])
    return rows[index] if 0 <= index < len(rows) else None


def _run_judge(
    *,
    trace_json: dict,
    stage_keys: list[str],
    task_id: str,
    trace_id: str,
    env: str,
    workers: int,
    trace_meta: dict[str, Any] | None = None,
) -> None:
    """선택한 단계를 채점하고 진행을 보여준다. 저장은 [review.judge][app.tasks.review.judge] 가 한다."""
    progress = st.progress(0.0, text="채점 준비 중…")
    done = 0

    def on_stage(stage_key: str, _error: Exception | None) -> None:
        nonlocal done
        done += 1
        progress.progress(done / len(stage_keys), text=f"{stages.get(stage_key).label} 완료 ({done}/{len(stage_keys)})")

    try:
        outcome = review.judge(
            trace_json=trace_json,
            stage_keys=stage_keys,
            task_id=task_id,
            trace_id=trace_id,
            env=env,
            workers=workers,
            trace_meta=trace_meta,
            on_stage=on_stage,
        )
    except JudgeProviderError as exc:
        progress.empty()
        st.error(f"채점 실패 [{exc.code}]: {exc}")
        return
    progress.empty()

    composite = (outcome.record.get("composite") or {}).get("score")
    st.toast(f"채점 저장 — 종합 {composite if composite is not None else '-'}/100")
    if outcome.failures:
        failures = [
            f"{stages.get(key).label}: {type(error).__name__}: {error}"
            for key, error in outcome.failures.items()
        ]
        st.warning("일부 단계가 실패했습니다:\n\n" + "\n".join(f"- {item}" for item in failures))


def _render_stage(
    *,
    stage_evidence: Any,
    record: dict[str, Any] | None,
    trace_id: str,
    on_judge: Any,
) -> None:
    """단계 하나: 근거와 결과를 나란히 보여주고 그 자리에서 채점한다."""
    spec = stage_evidence.stage
    entry = evaluation_record.stage_score(record or {}, spec.key) or {}
    card = entry.get("scorecard") or {}
    total = card.get("total")
    state = "채점 전" if not card else (f"{total}/100" if total is not None else "N/A")
    label = f"{spec.label} · {state}"
    if not stage_evidence.applicable:
        label = f"{spec.label} · 근거 없음"

    with st.expander(label, expanded=False):
        head_left, head_right = st.columns([3, 1], vertical_alignment="center")
        head_left.caption(
            f"{spec.total_points}점 만점 · 항목 {len(spec.items)}개 · 기준 문서 {', '.join(spec.doc_sections)}절"
            + (f" · 최근 채점 {entry.get('judgedAt', '')[:16]}" if entry.get("judgedAt") else "")
        )
        if head_right.button(
            "이 단계 채점",
            key=f"judge_{spec.key}_{trace_id}",
            width="stretch",
            disabled=not stage_evidence.applicable,
        ):
            on_judge([spec.key])

        evidence_column, result_column = st.columns([1, 1], gap="medium", vertical_alignment="top")
        with evidence_column:
            st.markdown("**이 채점이 본 것**")
            stage_view.render_evidence(stage_evidence)
        with result_column:
            st.markdown("**채점 결과**")
            stage_view.render_scorecard(card)

        edit_key = f"rubric_edit_{spec.key}_{trace_id}"
        edited_mark = " · 수정됨" if stages.is_edited(spec.key) else ""
        with st.expander(
            f"채점 기준 · 항목 {len(spec.items)}개 / {spec.total_points}점{edited_mark}",
            expanded=bool(st.session_state.get(edit_key)),
        ):
            if st.session_state.get(edit_key):
                st.caption(
                    "항목·배점·확인 기준을 고쳐 저장하면 다음 채점부터 이 기준이 채점 프롬프트로 나갑니다."
                )
                stage_view.render_criteria_editor(spec, state_key=edit_key)
            else:
                stage_view.render_criteria(spec)
                if st.button("기준 수정", key=f"edit_{spec.key}_{trace_id}"):
                    st.session_state[edit_key] = True
                    st.rerun()


def render() -> None:
    st.title("Task 리뷰·채점")
    st.caption(
        "LangFuse 로그를 단계별로 잘라 Agent 마다 채점합니다. 목록에서 행을 클릭하면 "
        "원본 데이터 상태 · 각 단계가 본 근거 · 채점 결과가 아래에 함께 나타납니다."
    )
    stage_view.inject_css()

    traces = store.load_json(collection_file()) or []
    if not traces:
        st.info("먼저 **LangFuse 로그 수집** 페이지에서 로그를 수집하세요.")
        return

    env_col, scorable_col = st.columns([1, 2], vertical_alignment="bottom")
    with env_col:
        envs = env_filter.pick()
    with scorable_col:
        only_scorable = st.checkbox(
            "채점 대상만 보기",
            value=True,
            help=(
                "실제 실행(generate-timeline · update-user-memory)만 남깁니다. 나머지 이름은 대상 서버의 "
                "테스트 실행이 남긴 조각이라 채점해도 의미가 없습니다."
            ),
        )
    traces = environments.keep(traces, envs)
    scored = review.scored_index()
    summaries = _selectable_rows(traces, only_scorable=only_scorable, scored=scored)
    if not summaries:
        st.warning("조건에 맞는 트레이스가 없습니다. 필터를 끄거나 로그를 다시 수집하세요.")
        return
    judged = sum(1 for row in summaries if row.get("채점 여부") == "O")
    st.caption(
        f"{len(summaries):,}건 / 수집 {len(traces):,}건 · 채점 완료 {judged:,}건 · "
        f"미채점 {len(summaries) - judged:,}건"
    )

    frame = pd.DataFrame(display_rows(summaries), columns=list(_COLUMN_ORDER))
    event = st.dataframe(
        frame,
        width="stretch",
        height=_TABLE_HEIGHT,
        hide_index=True,
        column_config={
            "env": st.column_config.TextColumn("env", width="small"),
            "task_time": st.column_config.TextColumn("task_time", width="small"),
            "total_cost": st.column_config.TextColumn("total_cost", width="small"),
            "채점 여부": st.column_config.TextColumn("채점 여부", width="small"),
            "채점 시각": st.column_config.TextColumn("채점 시각", width="small"),
        },
        on_select="rerun",
        selection_mode="single-row",
        # 선택은 행 위치로 돌아오므로 필터가 바뀌면 key 를 바꿔 옛 선택이 다른 행을 가리키지 않게 한다.
        key=f"tr_table_{'-'.join(envs)}_{int(only_scorable)}",
    )

    summary = _picked_row(summaries, event.selection)
    if summary is None:
        st.info("위 목록에서 행을 클릭하면 여기에 원본 상태·근거·채점이 나타납니다.")
        return
    selected = str(summary["id"])
    env = environments.of(summary)

    detail_cache = st.session_state.setdefault("tr_detail", {})
    if selected not in detail_cache:
        try:
            with st.spinner(f"상세 조회 중… ({environments.label(env)})"):
                detail_cache[selected] = get_trace(selected, env)
        except Exception as exc:  # noqa: BLE001
            st.error(f"상세 조회 실패: {type(exc).__name__}: {exc}")
            return
    detail = detail_cache[selected]
    task_id = review.domain_task_id(detail, selected)

    tj_cache = st.session_state.setdefault("tr_tracejson", {})
    if selected not in tj_cache:
        tj_cache[selected] = build_trace_json(detail)
    trace_json = tj_cache[selected]

    st.divider()
    st.markdown(
        f"### {getattr(detail, 'name', None) or '(이름없음)'}  ·  task `{task_id}`  ·  "
        f"{environments.label(env)}"
    )

    stage_view.render_source_status(trace_json)
    stage_view.render_run_cost(trace_json, summary)

    with st.expander(f"처리 과정 (steps {len(trace_json['process']['steps'])}개)", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "순서": step["order"],
                        "단계": step["name"],
                        "유형": step["type"],
                        "상태": step.get("level"),
                        "구분": ", ".join(f"{k}={v}" for k, v in (step.get("metadata") or {}).items()),
                        "GEN": len(step["generationRefs"]),
                    }
                    for step in trace_json["process"]["steps"]
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption("최종 타임라인")
        st.json(trace_json["result"]["timeline"] or {}, expanded=False)

    evidences = {item.key: item for item in evidence_mod.build_all(trace_json)}
    record = evaluation_record.load(task_id)
    if record is not None and evaluation_record.is_legacy(record):
        st.warning(
            "이 Task 에는 구버전(7기준 0~10점) 채점 결과가 있습니다. 읽기 전용이며, 새로 채점하면 "
            "단계별 결과로 다시 쌓입니다."
        )
        record = None

    st.subheader("단계별 채점")
    composite = (record or {}).get("composite") or {}
    head = st.columns(4)
    head[0].metric("종합 스코어", f"{composite.get('score')}/100" if composite.get("score") is not None else "-")
    head[1].metric("채점한 단계", f"{composite.get('evaluatedCount', 0)}/{len(evidences)}")
    head[2].metric("채점 가능", sum(1 for item in evidences.values() if item.applicable))
    head[3].metric("LLM", llm_provider_label().split(" · ")[0])

    st.caption("토큰·실행(초)은 대상 서버가 그 단계에 쓴 값입니다. 비용은 트레이스 단위라 위에만 나옵니다.")
    stage_view.wrapped_table(
        stage_view.stage_rows(list(evidences.values()), record),
        (
            ("stage", "평가 대상", 17),
            ("input", "입력", 20),
            ("state", "근거 상태", 19),
            ("_num_tokens", "토큰 입력/출력(합계)", 14),
            ("_num_seconds", "실행(초)", 8),
            ("_num_total", "총점", 9),
            ("judged", "채점 시각", 13),
        ),
    )

    def judge(stage_keys: list[str]) -> None:
        _run_judge(
            trace_json=trace_json,
            stage_keys=stage_keys,
            task_id=task_id,
            trace_id=selected,
            env=env,
            workers=int(st.session_state.get(f"workers_{selected}", 3)),
            trace_meta={
                "cost": summary.get("total_cost"),
                "latency": summary.get("latency"),
                "tokens": ((trace_json.get("operation") or {}).get("tokenUsage") or {}).get("totalTokens"),
            },
        )
        st.rerun()

    setup_error = llm_setup_error()
    run_column, worker_column, note_column = st.columns([1, 1, 2], vertical_alignment="bottom")
    scorable = [key for key, item in evidences.items() if item.applicable]
    if run_column.button(
        f"전체 채점 ({len(scorable)}개 단계)",
        type="primary",
        disabled=bool(setup_error) or not scorable,
        width="stretch",
        key=f"judge_all_{selected}",
    ):
        judge(scorable)
    worker_column.number_input(
        "동시 실행", min_value=1, max_value=8, value=3, key=f"workers_{selected}",
        help="단계 하나에 수 분이 걸립니다. 동시에 몇 개까지 돌릴지 정합니다.",
    )
    note_column.caption(
        f"LLM Provider: {llm_provider_label()}" + (f"\n\n{setup_error}" if setup_error else "")
    )

    for item in evidences.values():
        _render_stage(
            stage_evidence=item,
            record=record,
            trace_id=selected,
            on_judge=judge,
        )
