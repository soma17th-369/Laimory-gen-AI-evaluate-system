"""LangFuse 로그를 누적 수집해 모든 페이지가 공유하는 저장소로 쌓는다.

한 번 저장한 로그는 지우지 않는다. 처음에는 쌓여 있는 로그를 전부 받아 저장하고, 그 다음부터는
마지막으로 저장한 로그 이후에 새로 생긴 것만 내려받아 합친다(→ [app.collect.sync][]).
조회 필터는 두지 않는다. 화면은 최신화 버튼과 저장 현황만 보여준다.

**키가 설정된 LangFuse 프로젝트를 한 번에 모두** 받아 한 목록에 합친다(→ [app.environments][]).
목록은 환경과 무관하게 시간순이고, 어디서 온 로그인지는 `env` 열로 구분한다. 진행 상태(커서)만
환경마다 따로라 한쪽을 다시 훑어도 다른 쪽 진행이 밀리지 않는다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import environments
from app.collect import sync as collect
from app.config import get_settings


def _fmt_time(value: str | None) -> str:
    """저장된 ISO 시각을 로컬 시간 문자열로. 없으면 '-'."""
    parsed = collect.parse_timestamp(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S") if parsed else "-"


def _run(envs: list[str], *, full: bool, backfill: bool) -> None:
    """설정된 환경을 차례로 동기화하고 결과를 알린다. 저장은 [app.collect.sync.sync][] 가 담당."""
    label = "전체 로그 수집" if backfill else "새 로그 동기화"
    try:
        with st.status(f"{label} 중…", expanded=False) as status:
            def on_progress(env: str, pages: int, fetched: int) -> None:
                status.update(
                    label=f"{label} 중… {environments.label(env)} · {pages}페이지 · {fetched}건 조회"
                )

            results = collect.sync_all(envs, full=full, on_progress=on_progress)
            status.update(label=f"{label} 완료", state="complete")
    except Exception as exc:  # noqa: BLE001
        st.error(f"수집 실패: {type(exc).__name__}: {exc}")
        return

    for result in results:
        mode = "전체 수집" if result.mode == "backfill" else "증분 수집"
        st.success(
            f"{environments.label(result.environment)} · {mode} · "
            f"신규 {result.added}건 · 갱신 {result.updated}건 → 이 환경 {result.total:,}건 저장됨"
        )
        if not result.completed:
            st.warning(
                f"{environments.label(result.environment)}: 마지막 페이지까지 가지 못했습니다. "
                "다시 실행하면 멈춘 지점부터 이어받습니다."
            )
    if results and not any(r.added or r.updated for r in results):
        st.info("새로 생긴 로그가 없습니다.")


def _status_table(states: dict[str, dict], counts: dict[str, int], configured: list[str]) -> pd.DataFrame:
    """환경별 수집 현황 한 표."""
    return pd.DataFrame(
        [
            {
                "환경": environments.label(env),
                "키 설정": "○" if env in configured else "-",
                "저장된 로그": f"{counts.get(env, 0):,}",
                "마지막 로그 시각": _fmt_time((states.get(env) or {}).get("last_timestamp")),
                "마지막 동기화": _fmt_time((states.get(env) or {}).get("last_synced_at")),
            }
            for env in environments.ENVIRONMENTS
        ]
    )


def render() -> None:
    st.title("📥 LangFuse 로그 수집")
    st.caption("여기서 쌓은 로그를 대시보드·Task 리뷰·테스트 데이터 페이지가 함께 사용합니다.")
    st.info(
        "저장된 로그는 지우지 않고 계속 쌓입니다. 처음에는 LangFuse에 쌓인 로그를 전부 받아오고, "
        "그 다음부터는 마지막으로 저장한 로그 이후에 새로 생긴 것만 내려받습니다. "
        "키가 설정된 프로젝트(개발·운영)를 모두 받아 한 목록에 합칩니다."
    )

    configured = get_settings().configured_environments()
    states = collect.load_states()
    backfill_needed = any(collect.needs_backfill(states.get(env, {})) for env in configured)

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
        _run(configured, full=run_full, backfill=run_full or backfill_needed)
        states = collect.load_states()

    missing = [env for env in environments.ENVIRONMENTS if env not in configured]
    if missing:
        names = " · ".join(
            f"LANGFUSE_{env.upper()}_PUBLIC_KEY / LANGFUSE_{env.upper()}_SECRET_KEY"
            for env in missing
        )
        labels = ", ".join(environments.label(env) for env in missing)
        if configured:
            st.warning(f"키가 없어 수집하지 않는 환경: {labels}. .env 에 {names} 를 설정하면 함께 수집합니다.")
        else:
            st.error(f"수집할 수 있는 환경이 없습니다. .env 에 {names} 를 설정하세요.")

    rows = collect.load_rows()
    if not rows:
        st.info("아직 저장된 로그가 없습니다.")
        return

    counts = {env: len(collect.rows_of(rows, env)) for env in environments.ENVIRONMENTS}

    metric_cols = st.columns(2 + len(environments.ENVIRONMENTS))
    metric_cols[0].metric("저장된 로그", f"{len(rows):,}")
    metric_cols[1].metric("taskId", len({row.get("taskId") for row in rows if row.get("taskId")}))
    for column, env in zip(metric_cols[2:], environments.ENVIRONMENTS):
        column.metric(environments.label(env), f"{counts[env]:,}")

    st.subheader("환경별 수집 현황")
    st.dataframe(_status_table(states, counts, configured), width="stretch", hide_index=True)

    st.subheader("저장된 로그 목록")
    st.caption("환경과 무관하게 최신순입니다. `env` 열이 어느 프로젝트에서 온 로그인지 알려줍니다.")
    frame = pd.DataFrame(rows)
    if "env" in frame.columns:
        frame["env"] = frame["env"].fillna(environments.DEV)
    st.dataframe(frame, width="stretch", hide_index=True)
