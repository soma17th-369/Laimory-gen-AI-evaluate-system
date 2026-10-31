"""단계별 채점 화면의 공용 렌더러.

Task 리뷰(채점 실행)와 채점 결과(저장분 조회)가 **같은 방식으로** 보여줘야 한다. 무엇을 보고
채점했는지가 두 화면에서 다르게 보이면 근거를 믿을 수 없기 때문이다. 그래서 다음 셋을 여기서만
그린다.

1. **원본 데이터의 상태** — 이 Task 가 애초에 무엇을 받았는지(수집 원본 건수·User Memory·window).
2. **이 단계가 본 근거** — [app.analysis.evidence][] 가 자른 그대로. 채점 프롬프트에 들어간 것과
   같은 내용·같은 순서다.
3. **채점 결과** — 항목별 점수와 이유, 감점 근거, 별도 알림.

긴 한국어 이유가 가로로 잘리지 않게 표는 HTML 로 그린다(`st.dataframe` 은 셀을 자른다).
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from app.analysis import rubric_store, stages
from app.analysis.evidence import StageEvidence
from app.analysis.stage_schema import ALERT_LABELS

TABLE_CSS = """
<style>
.stage-table { width: 100%; margin: 0.35rem 0 1rem; overflow-x: clip; }
.stage-table table {
    width: 100%; table-layout: fixed; border-collapse: collapse;
    font-size: 0.86rem; line-height: 1.45;
}
.stage-table th, .stage-table td {
    border: 1px solid rgba(128, 128, 128, 0.28); padding: 0.5rem 0.6rem;
    text-align: left; vertical-align: top;
    white-space: normal; word-break: keep-all; overflow-wrap: anywhere;
}
.stage-table th { background: rgba(128, 128, 128, 0.12); font-weight: 600; }
.stage-table td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.stage-note { color: rgba(128,128,128,0.95); font-size: 0.82rem; margin: -0.2rem 0 0.4rem; }
</style>
"""

_SOURCE_LABELS = {
    "stays": "체류",
    "movements": "이동",
    "calendars": "캘린더",
    "notifications": "알림",
    "photos": "사진",
    "healths": "건강",
}


def inject_css() -> None:
    st.markdown(TABLE_CSS, unsafe_allow_html=True)


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return escape(str(value)).replace("\n", "<br>")


def wrapped_table(rows: list[dict[str, Any]], columns: tuple[tuple[str, str, int], ...]) -> None:
    """가로 스크롤 없이 셀 높이가 내용에 맞춰 늘어나는 표. columns = (key, 라벨, 폭%)."""
    if not rows:
        return
    colgroup = "".join(f'<col style="width:{width}%">' for _, _, width in columns)
    header = "".join(f"<th>{escape(label)}</th>" for _, label, _ in columns)
    body = ""
    for row in rows:
        cells = ""
        for key, _, _ in columns:
            css = " class=\"num\"" if key.startswith("_num_") else ""
            cells += f"<td{css}>{_cell(row.get(key))}</td>"
        body += f"<tr>{cells}</tr>"
    st.markdown(
        f'<div class="stage-table"><table><colgroup>{colgroup}</colgroup>'
        f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def source_status(trace_json: dict) -> dict[str, Any]:
    """수집 원본의 상태. 어떤 단계가 왜 N/A 인지 여기서 바로 읽힌다."""
    source = trace_json.get("source") or {}
    task = trace_json.get("task") or {}
    memory = source.get("userMemory") or {}
    counts = {key: len(source.get(key) or []) for key in _SOURCE_LABELS}
    return {
        "counts": counts,
        "date": source.get("date"),
        "timezone": source.get("timezone"),
        "window": task.get("window") or {},
        "userMemory": {
            "captured": bool(memory.get("contentCaptured")),
            "filledFieldCount": memory.get("filledFieldCount"),
            "byteLength": memory.get("byteLength"),
        },
        "status": (trace_json.get("operation") or {}).get("status"),
        "traceName": task.get("traceName"),
    }


def render_source_status(trace_json: dict) -> None:
    """① 원본 데이터의 상태."""
    status = source_status(trace_json)
    window = status["window"] or {}
    st.markdown("**수집 원본 상태**")
    st.markdown(
        f'<div class="stage-note">{escape(str(status["date"] or "-"))} '
        f'{escape(str(status["timezone"] or ""))} · window '
        f'{escape(str(window.get("start") or "-"))} ~ {escape(str(window.get("end") or "-"))} · '
        f'실행 상태 {escape(str(status["status"] or "-"))}</div>',
        unsafe_allow_html=True,
    )
    columns = st.columns(len(_SOURCE_LABELS) + 1)
    for column, (key, label) in zip(columns, _SOURCE_LABELS.items()):
        column.metric(label, status["counts"][key])
    memory = status["userMemory"]
    columns[-1].metric(
        "User Memory",
        "원문 있음" if memory["captured"] else "해시만",
        help="수집 원본에는 해시만 남는다. 원문은 각 단계의 프롬프트 안에서만 확인된다.",
    )


def render_run_cost(trace_json: dict, trace_row: dict[str, Any] | None = None) -> None:
    """대상 파이프라인이 이 Task 에 쓴 비용. 점수와 무관한 기록이라 따로 묶어 보여준다.

    토큰은 트레이스의 집계값(`operation.tokenUsage`)이고, 시간(초)과 비용(USD)은 LangFuse 가
    트레이스 단위로 계산한 값이다. 비용은 단계별로 나뉘지 않는다.
    """
    tokens = (trace_json.get("operation") or {}).get("tokenUsage") or {}
    latency = (trace_row or {}).get("latency")
    cost = (trace_row or {}).get("total_cost")
    st.markdown("**대상 실행 비용** (Timeline·User Memory 생성에 쓴 값. 채점 점수와 무관)")
    columns = st.columns(4)
    columns[0].metric(
        "총 토큰", f"{tokens['totalTokens']:,}" if tokens.get("totalTokens") else "-"
    )
    columns[1].metric(
        "입력 / 출력 토큰",
        f"{tokens.get('inputTokens') or 0:,} / {tokens.get('outputTokens') or 0:,}",
    )
    columns[2].metric(
        "실행 시간", f"{latency:.1f}초" if isinstance(latency, (int, float)) else "-"
    )
    columns[3].metric(
        "비용", f"${cost:.4f}" if isinstance(cost, (int, float)) else "-",
        help="LangFuse 가 계산한 트레이스 전체 비용(USD)입니다. 단계별로는 나뉘지 않습니다.",
    )


def _as_text(payload: Any) -> str:
    if payload is None:
        return "(없음)"
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(payload)


def render_evidence(stage_evidence: StageEvidence) -> None:
    """② 이 채점이 정확히 무엇을 봤는지. 프롬프트에 들어간 근거와 같은 내용·같은 순서다."""
    if not stage_evidence.applicable:
        st.info(f"채점하지 않음 — {stage_evidence.skip_reason}")
        return

    if stage_evidence.summary:
        st.markdown(
            '<div class="stage-note">'
            + escape(" · ".join(f"{key} {value}" for key, value in stage_evidence.summary.items()))
            + "</div>",
            unsafe_allow_html=True,
        )
    for index, section in enumerate(stage_evidence.sections):
        with st.expander(section.title, expanded=index in (1, 2)):
            st.caption(section.note)
            payload = section.payload
            if payload is None:
                st.caption("(근거 없음)")
            elif isinstance(payload, str):
                st.code(payload)
            else:
                st.json(payload, expanded=False)
    from app.analysis.deterministic_checks import confirmed_checks

    confirmed = confirmed_checks(stage_evidence)
    if confirmed:
        with st.expander("코드로 확인한 채점 근거", expanded=False):
            st.json(confirmed, expanded=False)


def render_scorecard(card: dict[str, Any]) -> None:
    """③ 채점 결과. 항목마다 점수와 이유가 반드시 보인다."""
    if not card:
        st.caption("아직 채점하지 않았습니다.")
        return
    if card.get("total") is None:
        st.info(f"채점하지 않음 — {card.get('skipReason') or '근거 없음'}")
        return

    st.markdown(f"**총점 {card['total']} / 100** — {card.get('summary') or ''}")
    if card.get("scoringPolicy"):
        st.caption("세부 기준별 통과율을 계산해 항목 점수로 환산했습니다. 항목 안의 적용 기준은 동일 가중치입니다.")
        with st.expander("세부 판정 건수와 근거 보기", expanded=False):
            st.json(card.get("checks") or {}, expanded=False)

    alerts = card.get("alerts") or []
    if alerts:
        counts: dict[str, int] = {}
        for item in alerts:
            kind = ALERT_LABELS.get(item.get("kind"), str(item.get("kind")))
            counts[kind] = counts.get(kind, 0) + 1
        st.error(
            "점수와 별개 알림 — "
            + " · ".join(f"{kind} {count}건" for kind, count in counts.items())
        )
        wrapped_table(
            [
                {
                    "kind": ALERT_LABELS.get(item.get("kind"), item.get("kind")),
                    "where": item.get("where"),
                    "detail": item.get("detail"),
                }
                for item in alerts
            ],
            (("kind", "종류", 22), ("where", "위치", 26), ("detail", "내용", 52)),
        )

    rows = []
    for item in card.get("items") or []:
        applied = item.get("applied")
        rows.append(
            {
                "label": item.get("label"),
                "_num_score": f"{item.get('score')}/{item.get('points')}" if applied else "N/A",
                "_num_applied": f"{item.get('appliedPoints')}" if applied else "0",
                "reason": item.get("reason"),
            }
        )
    wrapped_table(
        rows,
        (
            ("label", "항목", 22),
            ("_num_score", "점수", 10),
            ("_num_applied", "반영 배점", 10),
            ("reason", "이유", 58),
        ),
    )
    if card.get("redistributed"):
        st.caption(
            "평가할 입력이 없어 배점을 나머지 항목에 비례 배분한 항목: "
            + ", ".join(card["redistributed"])
        )

    deductions = card.get("deductions") or []
    if deductions:
        st.markdown("**감점 근거**")
        wrapped_table(
            [
                {
                    "itemKey": item.get("itemKey"),
                    "severity": item.get("severity"),
                    "description": item.get("description"),
                    "refs": ", ".join(item.get("sourceRefs") or []) or "-",
                    "path": item.get("outputPath"),
                }
                for item in deductions
            ],
            (
                ("itemKey", "항목", 14),
                ("severity", "심각도", 9),
                ("description", "문제", 39),
                ("refs", "입력 rawId", 20),
                ("path", "출력 위치", 18),
            ),
        )
    elif any(row.get("passed", 0) < row.get("total", 0) for checks in (card.get("checks") or {}).values() for row in checks.values()):
        st.warning("세부 판정에 위반이 있습니다. 위 항목별 이유와 판정 근거를 확인하세요.")
    else:
        st.success("감점 근거가 없습니다.")

def render_criteria(spec: Any) -> None:
    """채점 기준을 표로. 어떤 항목에 몇 점이 걸려 있고 무엇을 확인하는지 한눈에 본다."""
    source = "설정에서 고친 기준" if stages.is_edited(spec.key) else "메트릭 문서 기본값"
    st.markdown(
        f'<div class="stage-note">{escape(spec.label)} · 합계 {spec.total_points}점 · 항목 '
        f"{len(spec.items)}개 · {source}</div>",
        unsafe_allow_html=True,
    )
    wrapped_table(
        [
            {
                "label": entry.item.label,
                "_num_points": entry.item.points,
                "criteria": entry.text,
            }
            for entry in stages.criteria(spec)
        ],
        (("label", "항목", 22), ("_num_points", "배점", 8), ("criteria", "확인 기준", 70)),
    )


_EDITOR_COLUMNS = ("key", "label", "points", "criteria")


def _criteria_rows(spec: Any) -> list[dict[str, Any]]:
    return [
        {
            "key": entry.item.key,
            "label": entry.item.label,
            "points": entry.item.points,
            "criteria": entry.text,
        }
        for entry in stages.criteria(spec)
    ]


def render_criteria_editor(spec: Any, *, state_key: str) -> None:
    """채점 기준을 그 자리에서 고친다. 저장하면 다음 채점부터 그 내용이 프롬프트로 나간다.

    `state_key` 는 편집 모드를 켜 둔 session_state 키다. 저장·취소하면 지우고 화면을 다시 그린다.
    """
    editor_key = f"{state_key}_editor"
    from app.analysis.stage_judge import default_rubric

    with st.expander("현재 채점 프롬프트 · 계산 규칙과 예시", expanded=False):
        st.caption("현재 저장된 기준으로 다음 채점에 전달할 원문입니다. 아래 편집 내용은 저장 후 반영됩니다.")
        st.code(default_rubric(spec), language="markdown", wrap_lines=True)
    frame = st.data_editor(
        pd.DataFrame(_criteria_rows(spec), columns=list(_EDITOR_COLUMNS)),
        key=editor_key,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "key": st.column_config.TextColumn(
                "항목 키",
                help="채점 결과의 field 이름입니다. 영문·숫자·밑줄만 쓸 수 있고 중복될 수 없습니다.",
                width="small",
            ),
            "label": st.column_config.TextColumn("항목", width="small"),
            "points": st.column_config.NumberColumn(
                "배점",
                help="합계가 100점이어야 저장됩니다.",
                min_value=0,
                max_value=100,
                step=1,
                width="small",
            ),
            "criteria": st.column_config.TextColumn(
                "확인 기준", help="채점자가 이 문장을 그대로 적용합니다. 비워 둘 수 없습니다.", width="large"
            ),
        },
    )

    rows = [
        {column: record.get(column) for column in _EDITOR_COLUMNS}
        for record in frame.to_dict("records")
        if str(record.get("key") or "").strip() or str(record.get("criteria") or "").strip()
    ]
    total = sum(int(row.get("points") or 0) for row in rows)
    if total != rubric_store.TOTAL_POINTS:
        st.warning(f"배점 합계가 {total}점입니다. 100점에 맞춰야 저장할 수 있습니다.")
    else:
        st.caption(f"배점 합계 {total}점 · 항목 {len(rows)}개")

    save_column, cancel_column, reset_column = st.columns(3)
    if save_column.button("저장", type="primary", width="stretch", key=f"{state_key}_save"):
        try:
            rubric_store.save(spec.key, rows)
        except rubric_store.RubricEditError as exc:
            st.error(f"저장하지 않았습니다 — {exc}")
        else:
            st.session_state.pop(state_key, None)
            st.toast("채점 기준을 저장했습니다. 다음 채점부터 이 기준으로 매깁니다.")
            st.rerun()

    if cancel_column.button("취소", width="stretch", key=f"{state_key}_cancel"):
        st.session_state.pop(state_key, None)
        st.rerun()

    if reset_column.button(
        "문서 기본값으로",
        width="stretch",
        disabled=not stages.is_edited(spec.key),
        key=f"{state_key}_reset",
        help="메트릭 문서의 원래 항목으로 되돌립니다.",
    ):
        rubric_store.reset(spec.key)
        st.session_state.pop(state_key, None)
        st.toast("메트릭 문서 기본값으로 되돌렸습니다.")
        st.rerun()


def stage_rows(
    evidences: list[StageEvidence],
    record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """단계 목록 표 한 줄씩. 근거 상태와 채점 상태를 한 눈에 본다."""
    stages_record = (record or {}).get("stages") or {}
    rows = []
    for item in evidences:
        card = (stages_record.get(item.key) or {}).get("scorecard") or {}
        total = card.get("total")
        usage = item.usage or {}
        duration_ms = usage.get("durationMs")
        rows.append(
            {
                "stage": item.stage.label,
                "input": " · ".join(f"{key} {value}" for key, value in item.summary.items()) or "-",
                "state": "채점 가능" if item.applicable else f"N/A — {item.skip_reason}",
                # 대상 서버가 이 단계에 쓴 비용. 점수와 무관한 기록이다.
                # 줄바꿈은 _cell 이 <br> 로 바꿔 준다(직접 태그를 넣으면 escape 된다).
                "_num_tokens": (
                    f"{usage.get('inputTokens') or 0:,} / {usage.get('outputTokens') or 0:,}"
                    "\n"
                    f"(합계 {usage['totalTokens']:,})"
                    if usage.get("totalTokens")
                    else "-"
                ),
                "_num_seconds": (
                    f"{duration_ms / 1000:.1f}" if isinstance(duration_ms, (int, float)) else "-"
                ),
                "_num_total": f"{total}/100" if total is not None else "-",
                "judged": ((stages_record.get(item.key) or {}).get("judgedAt") or "-")[:16],
            }
        )
    return rows
