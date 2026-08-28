"""LangFuse 로그를 누적 수집해 모든 페이지가 공유하는 저장소로 쌓는다.

한 번 저장한 로그는 지우지 않는다. 처음에는 쌓여 있는 로그를 전부 받아 저장하고, 그 다음부터는
마지막으로 저장한 로그 이후에 새로 생긴 것만 내려받아 합친다(→ [app.collect.sync][]).
조회 필터는 두지 않는다. 화면은 최신화 버튼과 저장 현황만 보여준다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.collect import sync as collect
from app.config import get_settings
from app.langfuse_client import LangfuseNotConfigured


def _fmt_time(value: str | None) -> str:
    """저장된 ISO 시각을 로컬 시간 문자열로. 없으면 '-'."""
    parsed = collect.parse_timestamp(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S") if parsed else "-"


def _run(*, full: bool, backfill: bool) -> None:
    """동기화를 실행하고 결과를 알린다. 저장은 [app.collect.sync.sync][] 가 담당."""
    label = "전체 로그 수집" if backfill else "새 로그 동기화"
    try:
        with st.status(f"{label} 중…", expanded=False) as status:
            def on_progress(pages: int, fetched: int) -> None:
                status.update(label=f"{label} 중… {pages}페이지 · {fetched}건 조회")

            result = collect.sync(full=full, on_progress=on_progress)
            status.update(label=f"{label} 완료 · {result.pages}페이지 조회", state="complete")
    except LangfuseNotConfigured as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"수집 실패: {type(exc).__name__}: {exc}")
        return

    mode = "전체 수집" if result.mode == "backfill" else "증분 수집"
    st.success(
        f"{mode} · 신규 {result.added}건 · 갱신 {result.updated}건 → 총 {result.total}건 저장됨"
    )
    if not result.completed:
        st.warning("마지막 페이지까지 가지 못했습니다. 다시 실행하면 멈춘 지점부터 이어받습니다.")
    elif not result.added and not result.updated:
        st.info("새로 생긴 로그가 없습니다.")


def render() -> None:
    st.title("📥 LangFuse 로그 수집")
    st.caption("여기서 쌓은 로그를 대시보드·Task 리뷰·테스트 데이터 페이지가 함께 사용합니다.")
    st.info(
        "저장된 로그는 지우지 않고 계속 쌓입니다. 처음에는 LangFuse에 쌓인 로그를 전부 받아오고, "
        "그 다음부터는 마지막으로 저장한 로그 이후에 새로 생긴 것만 내려받습니다."
    )

    configured = get_settings().has_langfuse_credentials()
    state = collect.load_state()
    backfill_needed = collect.needs_backfill(state)

    button_cols = st.columns(2)
    with button_cols[0]:
        run_sync = st.button(
            "전체 로그 수집" if backfill_needed else "새 로그 동기화",
            key="collect_sync",  # 라벨이 모드에 따라 바뀌므로 key 로 위젯 id 를 고정한다
            type="primary",
            disabled=not configured,
            width="stretch",
        )
    with button_cols[1]:
        run_full = st.button(
            "처음부터 다시 훑기",
            key="collect_full",
            disabled=not configured,
            width="stretch",
            help="커서를 무시하고 전체를 다시 확인해 빠진 로그를 채웁니다. 저장된 로그는 지우지 않습니다.",
        )

    if run_sync or run_full:
        _run(full=run_full, backfill=run_full or backfill_needed)
        state = collect.load_state()

    if not configured:
        st.warning(".env에 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY를 설정하세요.")

    rows = collect.load_rows()
    if not rows:
        st.info("아직 저장된 로그가 없습니다.")
        return

    metric_cols = st.columns(4)
    metric_cols[0].metric("저장된 로그", len(rows))
    metric_cols[1].metric("taskId", len({row.get("taskId") for row in rows if row.get("taskId")}))
    metric_cols[2].metric("마지막 로그 시각", _fmt_time(state.get("last_timestamp")))
    metric_cols[3].metric("마지막 동기화", _fmt_time(state.get("last_synced_at")))

    st.subheader("저장된 로그 목록")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
