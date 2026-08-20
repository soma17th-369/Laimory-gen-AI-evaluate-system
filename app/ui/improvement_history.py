"""⑤ 개선 history — 반영된 개선책을 시간 순으로 놓고 전후 결과를 비교한다.

개선책마다 `[반영 시각, 다음 개선책 반영 시각)` 구간을 맡는다. 그 구간의 실제 로그를 나열하고,
직전 구간과 비교해 점수·비용·토큰·latency 가 어떻게 달라졌는지 보여준다(→ [app.improve.compare][]).

모델과 토큰은 트레이스 목록에 없어서 필요할 때만 관측치를 조회해 채운다
(→ [app.collect.generations][]). 조회하지 않은 행은 `-` 로 남는다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.collect import generations
from app.collect import sync as collect
from app.collect.sync import parse_timestamp
from app.improve import compare, records
from app.storage import store
from app.storage.paths import evaluations_dir

_ROW_LIMIT = 50
"""구간마다 화면에 먼저 보여줄 결과 수. 모델·토큰 조회 대상도 이 목록이다."""


def _load_evaluations() -> dict[str, dict]:
    """taskId → 평가. 채점한 task 만 들어 있다."""
    out: dict[str, dict] = {}
    for path in store.list_json(evaluations_dir()):
        data = store.load_json(path)
        if isinstance(data, dict) and data.get("taskId"):
            out[str(data["taskId"])] = data
    return out


def _fmt_time(value) -> str:
    parsed = parse_timestamp(value) if isinstance(value, str) or value is None else value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M") if parsed else "-"


def _fmt_value(key: str, value: float | None) -> str:
    """지표별 표시 형식. 값이 없으면 '-'."""
    if value is None:
        return "-"
    if key in ("traces",):
        return f"{int(value):,}"
    if key in ("tokens_avg",):
        return f"{value:,.0f}"
    if key in ("cost_avg", "cost_sum"):
        return f"{value:.4f}"
    if key in ("latency_avg",):
        return f"{value:.2f}s"
    return f"{value:.2f}"


def _fmt_change(delta: compare.MetricDelta) -> str:
    """변화량과 방향. 표본이 없으면 '-'."""
    diff = delta.diff
    if diff is None:
        return "-"
    ratio = delta.ratio
    text = f"{diff:+,.4f}" if delta.key in ("cost_avg", "cost_sum") else f"{diff:+,.2f}"
    if ratio is not None:
        text += f" ({ratio:+.0%})"
    improved = delta.improved
    if improved is True:
        return f"🟢 {text}"
    if improved is False:
        return f"🔴 {text}"
    return text


def _delta_table(deltas: list[compare.MetricDelta], previous_label: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "지표": d.label,
                f"{previous_label}": f"{_fmt_value(d.key, d.before)}{d.unit}",
                "표본(이전)": d.n_before,
                "반영 이후": f"{_fmt_value(d.key, d.after)}{d.unit}",
                "표본(이후)": d.n_after,
                "변화": _fmt_change(d),
            }
            for d in deltas
        ]
    )


def _fetch_models(slug: str, trace_ids: list[str]) -> None:
    """표시 중인 결과 행의 모델·토큰을 조회해 캐시에 채운다(트레이스당 API 1회)."""
    try:
        with st.status(f"모델·토큰 조회 중… (최대 {len(trace_ids)}건)", expanded=False) as status:
            def on_progress(done: int, total: int) -> None:
                status.update(label=f"모델·토큰 조회 중… {done}/{total}")

            _, fetched = generations.fetch_missing(trace_ids, on_progress=on_progress)
            status.update(label=f"조회 완료 · 신규 {fetched}건", state="complete")
    except Exception as exc:  # noqa: BLE001
        st.error(f"조회 실패: {type(exc).__name__}: {exc}")
        return
    st.rerun()


def _render_segment(
    order: int,
    segment: compare.Segment,
    rows: list[dict],
    evaluations: dict[str, dict],
    rollup: dict[str, dict],
) -> None:
    slug = segment.slug
    after_rows = compare.rows_between(rows, segment.start, segment.end)
    before_rows = compare.rows_between(rows, segment.previous_start, segment.start)

    after = compare.aggregate(after_rows, evaluations=evaluations, rollup=rollup)
    before = compare.aggregate(before_rows, evaluations=evaluations, rollup=rollup)

    st.subheader(f"{order}. {slug}")
    window_end = _fmt_time(segment.end) if segment.end is not None else "현재"
    st.caption(f"반영 {_fmt_time(segment.start)} · 구간 {_fmt_time(segment.start)} ~ {window_end}")
    if segment.record.get("note"):
        st.markdown(f"> {segment.record['note']}")

    st.markdown(f"**{segment.previous_label} 대비 변화**")
    st.dataframe(
        _delta_table(compare.deltas(before, after), segment.previous_label),
        width="stretch",
        hide_index=True,
    )
    if after.score_n == 0:
        st.caption("이 구간에 채점된 task 가 없어 점수 비교는 비어 있습니다. Task 리뷰에서 채점하면 채워집니다.")

    criteria = compare.criterion_deltas(before, after)
    if criteria:
        with st.expander(f"채점 기준별 점수 ({after.score_n}개 task)"):
            st.dataframe(
                _delta_table(criteria, segment.previous_label), width="stretch", hide_index=True
            )

    if after.models:
        chips = " · ".join(f"`{name}` {count}건" for name, count in sorted(after.models.items()))
        st.markdown(f"**사용 모델** {chips}")

    st.markdown(f"**반영 이후 결과** ({len(after_rows):,}건 중 최신 {min(len(after_rows), _ROW_LIMIT)}건)")
    listed = compare.result_rows(
        after_rows, evaluations=evaluations, rollup=rollup, limit=_ROW_LIMIT
    )
    if not listed:
        st.info("이 구간에 수집된 로그가 없습니다.")
    else:
        st.dataframe(pd.DataFrame(listed), width="stretch", hide_index=True)
        missing = [r["traceId"] for r in listed if not r.get("모델") and r.get("traceId")]
        if missing:
            st.caption(f"모델·토큰이 비어 있는 행 {len(missing)}건. 조회하면 캐시에 저장돼 다음부터는 바로 보입니다.")
            if st.button(f"모델·토큰 조회 ({len(missing)}건)", key=f"hist_fetch_{slug}"):
                _fetch_models(slug, missing)

    with st.expander("트레이스 이름별 분해"):
        st.caption("단계마다 비용 규모가 달라서, 전체 평균만 보면 구성비 변화가 개선 효과처럼 보입니다.")
        breakdown = compare.name_breakdown(before_rows, after_rows)
        if breakdown:
            st.dataframe(pd.DataFrame(breakdown), width="stretch", hide_index=True)
        else:
            st.caption("비교할 로그가 없습니다.")

    with st.expander("개선책 본문"):
        st.markdown(segment.record.get("plan") or "(내용 없음)")


def render() -> None:
    st.title("📈 개선 history")
    st.caption("반영된 개선책을 시간 순으로 놓고, 반영 이후 결과가 실제로 달라졌는지 확인합니다.")

    rows = collect.load_rows()
    if not rows:
        st.info("먼저 **LangFuse 로그 수집** 페이지에서 로그를 수집하세요.")
        return

    applied = records.applied()
    if not applied:
        st.info(
            "반영 시기가 확정된 개선책이 없습니다. **개선책** 페이지의 '반영 상태' 탭에서 "
            "상태를 '반영됨' 으로 바꾸고 반영 시기를 지정하세요."
        )
        return

    evaluations = _load_evaluations()
    rollup = generations.load_rollup()
    segments = compare.segments(applied)

    st.caption(
        f"반영된 개선책 {len(segments)}개 · 수집 로그 {len(rows):,}건 · 채점된 task {len(evaluations)}개"
    )
    for order, segment in enumerate(segments, start=1):
        _render_segment(order, segment, rows, evaluations, rollup)
        st.divider()
