"""Dev 환경 테스트 — dev 서버의 타임라인 AI 테스트 엔드포인트를 이 앱에서 바로 불러 본다.

흐름: ① 요청 만들기(예시 또는 수집된 dev 트레이스의 원본 스냅샷) → 편집·검사 → ② 보내기 →
결과 → ③ 실행 기록. 결과의 `taskId` 는 LangFuse 트레이스와 이어지는 상관키라, 로그를 수집하면
Task 리뷰·채점에서 같은 실행을 채점할 수 있다. 호출 계약은 [app.devtest.client][] 를 본다.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from app import environments
from app.collect.sync import parse_timestamp
from app.config import get_settings
from app.devtest import client, request, runs
from app.langfuse_client import get_trace, missing_credentials_message
from app.storage import store
from app.storage.paths import collection_file

_BODY_KEY = "devtest_body"
_SOURCE_KEY = "devtest_source"
"""편집창에 마지막으로 불러온 것 — 출처와 불러온 원문(편집 여부 판단용)."""
_NOTE_KEY = "devtest_note"
_LAST_RUN_KEY = "devtest_last_run"

_TRACE_NAME = "generate-timeline"


def _pretty(body: Any) -> str:
    return json.dumps(body, ensure_ascii=False, indent=2)


def _fmt_time(value: Any) -> str:
    parsed = parse_timestamp(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M") if parsed else "-"


def _event_time(value: Any) -> str:
    """이벤트 시각은 서버가 준 offset 그대로 둔다."""
    if not isinstance(value, str):
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def _type_counts(counts: Counter) -> str:
    return " · ".join(f"{name} {count}" for name, count in sorted(counts.items())) or "-"


def event_rows(events: list[dict[str, Any]], source_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """결과 이벤트 표. 근거 원본은 요청의 itemType 으로 풀어 보여준다."""
    types = {item.get("rawId"): item.get("itemType") for item in source_items}
    rows = []
    for event in events:
        raw_ids = [str(raw_id) for raw_id in event.get("sourceRawIds") or []]
        rows.append(
            {
                "시작": _event_time(event.get("startAt")),
                "끝": _event_time(event.get("endAt")),
                "eventType": event.get("eventType"),
                "title": event.get("title"),
                "subtitle": event.get("subtitle"),
                "place": event.get("place"),
                "address": event.get("address"),
                "question": event.get("question"),
                "근거 원본": _type_counts(Counter(types.get(raw_id, "?") for raw_id in raw_ids)),
            }
        )
    return rows


def unused_sources(events: list[dict[str, Any]], source_items: list[dict[str, Any]]) -> Counter:
    """어느 이벤트의 `sourceRawIds` 에도 없는 원본, itemType 별 건수."""
    used = {str(raw_id) for event in events for raw_id in event.get("sourceRawIds") or []}
    return Counter(item.get("itemType") for item in source_items if item.get("rawId") not in used)


def source_label(source: Any) -> str:
    if not isinstance(source, dict):
        return "-"
    kind = source.get("kind")
    if kind == "example":
        label = "예시"
    elif kind == "trace":
        label = f"dev 트레이스 {str(source.get('taskId') or source.get('traceId') or '')[:8]}"
    elif kind == "history":
        label = f"이전 실행 {source.get('runId', '')}"
    else:
        label = "직접 입력"
    return f"{label} (편집)" if source.get("edited") else label


def _result_label(outcome: client.Outcome) -> str:
    if outcome.ok:
        return "성공 · timedOut" if outcome.timed_out else "성공"
    if outcome.status is None:
        return "응답 없음"
    return f"HTTP {outcome.status}" + (f" · AI {outcome.ai_error_code}" if outcome.ai_error_code else "")


def _source_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    body = record.get("request")
    items = body.get("sourceItems") if isinstance(body, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def run_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """실행 기록 표. 한 행 = 호출 한 번."""
    rows = []
    for record in records:
        outcome = client.Outcome.from_record(record.get("response") or {})
        rows.append(
            {
                "실행 시각": _fmt_time(record.get("startedAt")),
                "결과": _result_label(outcome),
                "소요(초)": round(outcome.elapsed_seconds, 1),
                "이벤트": str(len(outcome.events)) if outcome.ok else "-",
                "원본": len(_source_items(record)),
                "입력": source_label(record.get("source")),
                "taskId": outcome.task_id or "-",
            }
        )
    return rows


# ── 요청 만들기 ────────────────────────────────────────────────────────────────


def _set_body(body: Any, source: dict[str, Any], note: tuple[str, str] | None = None) -> None:
    """편집창 내용을 바꾼다. 편집창(text_area)이 그려지기 전이나 콜백에서만 부른다."""
    text = _pretty(body)
    st.session_state[_BODY_KEY] = text
    st.session_state[_SOURCE_KEY] = {**source, "text": text}
    st.session_state[_NOTE_KEY] = note


def _current_source(text: str) -> dict[str, Any]:
    loaded = st.session_state.get(_SOURCE_KEY)
    if not isinstance(loaded, dict):
        return {"kind": "manual"}
    source = {key: value for key, value in loaded.items() if key != "text"}
    source["edited"] = text != loaded.get("text")
    return source


def _dev_trace_rows() -> list[dict[str, Any]]:
    rows = store.load_json(collection_file()) or []
    picked = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("id")
        and row.get("name") == _TRACE_NAME
        and environments.of(row) == environments.DEV
    ]
    return sorted(picked, key=lambda row: str(row.get("timestamp") or ""), reverse=True)


def _load_from_trace(row: dict[str, Any]) -> None:
    try:
        trace = get_trace(row["id"], environments.DEV)
    except Exception as exc:  # noqa: BLE001
        st.session_state[_NOTE_KEY] = (
            "error",
            f"트레이스를 가져오지 못했습니다: {type(exc).__name__}: {exc} "
            "(30일이 지난 트레이스는 LangFuse 에서 지워졌을 수 있습니다)",
        )
        return
    snapshot = request.snapshot_from_observations(getattr(trace, "observations", None) or [])
    if snapshot is None:
        st.session_state[_NOTE_KEY] = (
            "error",
            "이 트레이스에는 원본 스냅샷(`normalize-source-snapshot`)이 없습니다.",
        )
        return
    body = request.body_from_snapshot(snapshot)
    note = (
        f"불러옴 — sourceItems {len(body['sourceItems'])}건. User Memory 는 LangFuse 에 해시만 남아 "
        "넣지 않았습니다(필요하면 `userMemory` 를 직접 추가)."
    )
    _set_body(
        body,
        {"kind": "trace", "traceId": row["id"], "taskId": row.get("taskId")},
        ("info", note),
    )


def _render_loader() -> None:
    st.subheader("① 요청 만들기")
    rows = _dev_trace_rows()
    by_id = {row["id"]: row for row in rows}
    has_langfuse = get_settings().has_langfuse_credentials(environments.DEV)
    pick_col, load_col, reset_col = st.columns([4, 1.4, 1.2], vertical_alignment="bottom")
    picked = pick_col.selectbox(
        "수집된 dev 트레이스의 원본 입력",
        options=list(by_id),
        index=None,
        placeholder="트레이스를 고르세요" if rows else "수집된 dev generate-timeline 트레이스가 없습니다",
        format_func=lambda trace_id: (
            f"{_fmt_time(by_id[trace_id].get('timestamp'))} · "
            f"task {str(by_id[trace_id].get('taskId') or '-')[:18]} · trace {trace_id[:8]}"
        ),
        key="devtest_trace",
    )
    if load_col.button("불러오기", disabled=not (picked and has_langfuse), width="stretch"):
        with st.spinner("LangFuse(dev)에서 원본 스냅샷을 가져오는 중…"):
            _load_from_trace(by_id[picked])
    if reset_col.button("예시로", width="stretch"):
        _set_body(request.example_body(), {"kind": "example"})
    if not has_langfuse:
        st.caption(missing_credentials_message(environments.DEV))

    if _BODY_KEY not in st.session_state:
        _set_body(request.example_body(), {"kind": "example"})
    note = st.session_state.get(_NOTE_KEY)
    if note:
        (st.error if note[0] == "error" else st.caption)(note[1])


def _render_editor() -> tuple[Any, request.Check | None, str]:
    text = st.text_area(
        "요청 body (JSON)",
        key=_BODY_KEY,
        height=360,
        help="고친 내용은 칸 밖을 누르거나 Ctrl+Enter 를 눌러야 반영됩니다.",
    )
    body, parse_error = request.parse(text)
    if parse_error:
        st.error(parse_error)
        return None, None, text
    check = request.validate(body)
    st.caption(
        f"sourceItems {sum(check.item_types.values())}건 ({_type_counts(Counter(check.item_types))}) · "
        f"{check.size_bytes / 1024:.1f}KB · 입력 {source_label(_current_source(text))}"
    )
    if check.errors:
        st.error("서버가 400 으로 돌려보낼 요청입니다.\n\n" + "\n".join(f"- {e}" for e in check.errors))
    if check.warnings:
        st.warning("\n".join(f"- {w}" for w in check.warnings))
    return body, check, text


# ── 보내기·결과 ────────────────────────────────────────────────────────────────


def _render_endpoint() -> client.Endpoint | None:
    endpoint = client.endpoint_from_settings()
    if endpoint is None:
        st.warning(
            "호출할 주소가 없습니다. `.env` 에 `TIMELINE_TEST_URL`(`…/t/api/{applicationVersion}/timeline/test` "
            "전체 주소)을 넣고 앱을 다시 띄우세요. 인증 토큰은 `TIMELINE_TEST_ACCESS_TOKEN` 에 넣으면 "
            "`Authorization: Bearer` 헤더로 나갑니다."
        )
        return None
    auth = "Bearer 토큰 붙임" if endpoint.has_token else "토큰 없음 — Authorization 헤더 없이 보냄"
    st.caption(f"대상 `{endpoint.url}` · {auth} · 제한 시간 {endpoint.timeout_seconds:.0f}초")
    return endpoint


def _reuse(record: dict[str, Any]) -> None:
    _set_body(record.get("request"), {"kind": "history", "runId": record.get("runId")})


def _render_run(record: dict[str, Any], *, key: str) -> None:
    outcome = client.Outcome.from_record(record.get("response") or {})
    items = _source_items(record)
    head = st.columns(4)
    head[0].metric(
        "결과",
        "성공" if outcome.ok else ("응답 없음" if outcome.status is None else str(outcome.status)),
    )
    head[1].metric("소요", f"{outcome.elapsed_seconds:.1f}초")
    head[2].metric("이벤트", len(outcome.events) if outcome.ok else "-")
    head[3].metric("원본", len(items))
    if outcome.ok:
        st.caption(
            f"taskId `{outcome.task_id or '-'}` — 이 값으로 LangFuse(dev) 트레이스를 찾을 수 있고, "
            "로그를 수집하면 **Task 리뷰·채점** 에서 채점할 수 있습니다."
        )
        if outcome.timed_out:
            st.info("timedOut — AI 가 제한 시간(120초)에 걸려 마지막 확정본을 돌려줬습니다. 실패는 아닙니다.")
        rows = event_rows(outcome.events, items)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        unused = unused_sources(outcome.events, items)
        if unused:
            st.caption(f"어느 이벤트에도 쓰이지 않은 원본: {_type_counts(unused)}")
    else:
        st.error(outcome.failure_text())

    with st.expander("요청·응답 원문"):
        st.caption(
            f"`{record.get('url')}` · 인증 {record.get('authorization')} · "
            f"입력 {source_label(record.get('source'))} · 실행 {record.get('runId')}"
        )
        req_col, res_col = st.columns(2)
        with req_col:
            st.markdown("**요청**")
            st.json(record.get("request"), expanded=False)
        with res_col:
            st.markdown("**응답**")
            if outcome.body is not None:
                st.json(outcome.body, expanded=False)
            elif outcome.text:
                st.code(outcome.text)
            else:
                st.caption("응답 본문 없음")
        buttons = st.columns(3)
        buttons[0].download_button(
            "요청 .json",
            data=_pretty(record.get("request")),
            file_name=f"request-{record.get('runId')}.json",
            mime="application/json",
            key=f"devtest_dl_req_{key}_{record.get('runId')}",
        )
        buttons[1].download_button(
            "응답 .json",
            data=_pretty(outcome.body) if outcome.body is not None else (outcome.text or ""),
            file_name=f"response-{record.get('runId')}.json",
            mime="application/json",
            key=f"devtest_dl_res_{key}_{record.get('runId')}",
        )
        buttons[2].button(
            "이 요청을 편집창으로",
            on_click=_reuse,
            args=(record,),
            key=f"devtest_reuse_{key}_{record.get('runId')}",
        )


def _render_send(endpoint: client.Endpoint | None, body: Any, check: request.Check | None, text: str) -> None:
    st.subheader("② 보내기")
    clicked = st.button(
        "dev 서버로 보내기",
        type="primary",
        disabled=endpoint is None or check is None or not check.ok,
    )
    st.caption(
        "실제 LLM 토큰 비용이 듭니다. 응답까지 수십 초 ~ 약 150초 걸리고, 실패해도 자동으로 다시 보내지 "
        "않습니다. 실행마다 요청·응답을 `data/dev-test/` 에 남깁니다."
    )
    if clicked and endpoint is not None:
        started_at = datetime.now().astimezone()
        with st.spinner("AI 추론을 기다리는 중… (최대 약 150초)"):
            outcome = client.send(endpoint, body)
            record = runs.save(
                endpoint=endpoint,
                body=body,
                outcome=outcome,
                source=_current_source(text),
                started_at=started_at,
            )
        st.session_state[_LAST_RUN_KEY] = record
    record = st.session_state.get(_LAST_RUN_KEY)
    if record:
        _render_run(record, key="last")


def _render_history() -> None:
    st.subheader("③ 실행 기록")
    records = runs.load_all()
    if not records:
        st.caption("아직 실행 기록이 없습니다.")
        return
    rows = run_rows(records)
    event = st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        height=min(320, 60 + 36 * len(rows)),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        # 새 실행이 생기면 행 위치가 밀리므로 선택을 초기화한다.
        key=f"devtest_runs_{len(records)}",
    )
    picked = list(getattr(event.selection, "rows", None) or [])
    if not picked:
        st.caption("행을 고르면 바로 아래에 그때의 결과가 나옵니다.")
        return
    _render_run(records[int(picked[0])], key="history")


def render() -> None:
    st.title("Dev 환경 테스트")
    st.caption(
        "dev 서버의 타임라인 AI 테스트 엔드포인트(`POST /t/api/{applicationVersion}/timeline/test`)에 "
        "입력을 보내 결과를 바로 봅니다. 서버 DB 에는 아무것도 저장되지 않습니다."
    )
    endpoint = _render_endpoint()
    _render_loader()
    body, check, text = _render_editor()
    _render_send(endpoint, body, check, text)
    _render_history()
