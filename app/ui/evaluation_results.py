"""채점 결과 — 지금까지 실행한 **모든 채점의 이력**.

Task 리뷰가 "지금 채점하고 근거를 보는 화면"이라면 여기는 "무엇을 언제 몇 점으로 매겼는지 쌓아
두는 화면"이다. 그래서 근거는 다시 그리지 않는다. 그건 Task 리뷰의 몫이고, 두 화면이 같은 일을
하면 역할이 겹친다.

**Task → 채점 실행 → 단계** 세 단계로 좁혀 본다. Task 하나에 채점 실행이 여러 번 쌓이고, 실행
하나가 여러 단계를 함께 채점할 수 있기 때문이다(`전체 채점` 한 번 = 실행 하나). 한 목록에 다 섞으면
어느 실행의 점수인지 알 수 없다.

같은 단계를 다시 채점해도 **덮어쓰지 않는다**(→ [app.analysis.evaluation_record.append_history][]).
채점자는 실행마다 점수가 달라지므로(같은 근거로 Repair 가 44.0 → 32.0 이 된 적이 있다) 실행 사이의
차이를 함께 보여준다.

점수 옆에는 **대상 파이프라인이 쓴 비용**(그 단계의 토큰·시간, Task 전체 토큰·시간·비용)을 함께
남긴다. LangFuse 로그에서 온 값이고 채점 점수에는 반영하지 않는다.

Task 목록은 환경 필터(→ [app.ui.env_filter][])를 따른다. 채점 이력 한 줄마다 그 Task 가 온 `env` 가
남아 있어서 그 값으로 거른다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app import environments
from app.analysis import evaluation_record
from app.ui import env_filter, stage_view


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _tokens(value: Any) -> str:
    return f"{value:,}" if isinstance(value, (int, float)) else "-"


def _seconds(milliseconds: Any) -> str:
    return f"{milliseconds / 1000:.1f}s" if isinstance(milliseconds, (int, float)) else "-"


def task_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """① Task 목록. Task 하나에 채점 실행이 몇 번 쌓였는지가 먼저 보여야 한다."""
    by_task: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_task.setdefault(str(run.get("taskId")), []).append(run)

    rows = []
    for task_id, items in by_task.items():
        latest = max(items, key=lambda run: run.get("judgedAt") or "")
        scores = [run["total"] for run in items if isinstance(run.get("total"), (int, float))]
        rows.append(
            {
                "Task": task_id,
                "날짜": latest.get("date") or "-",
                "채점 실행": len({run.get("runId") for run in items}),
                "채점 건수": len(items),
                "평균 총점": f"{_mean(scores)}" if scores else "-",
                "마지막 채점": (latest.get("judgedAt") or "")[:16].replace("T", " "),
                "Task 토큰": _tokens(latest.get("traceTokens")),
                "Task 비용": (
                    f"${latest['traceCost']:.4f}" if isinstance(latest.get("traceCost"), (int, float)) else "-"
                ),
                "env": environments.short_label(environments.of(latest)),
            }
        )
    rows.sort(key=lambda row: row["마지막 채점"], reverse=True)
    return rows


def run_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """② 그 Task 의 채점 실행 목록. 한 줄이 채점 한 번(여러 단계를 함께 채점했을 수 있다)."""
    by_run: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_run.setdefault(str(run.get("runId")), []).append(run)

    ordered = sorted(by_run.items(), key=lambda item: max(r.get("judgedAt") or "" for r in item[1]))
    rows = []
    previous: float | None = None
    for run_id, items in ordered:
        scores = [item["total"] for item in items if isinstance(item.get("total"), (int, float))]
        average = _mean(scores)
        diff = (
            f"{average - previous:+.1f}"
            if isinstance(average, float) and isinstance(previous, float)
            else ""
        )
        if isinstance(average, float):
            previous = average
        rows.append(
            {
                "채점 시각": max((item.get("judgedAt") or "") for item in items)[:16].replace("T", " "),
                "채점한 단계": len(items),
                "평균 총점": f"{average}" if average is not None else "-",
                "직전 실행 대비": diff,
                "단계별 점수": " · ".join(
                    f"{item.get('label', '')} {item['total']}"
                    for item in sorted(items, key=lambda i: i.get("stageKey") or "")
                    if isinstance(item.get("total"), (int, float))
                )
                or "-",
                "기준": "수정됨" if any(item.get("rubricEdited") for item in items) else "문서",
                "runId": run_id,
                "_items": items,
            }
        )
    rows.reverse()
    return rows


def stage_average_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """그 Task 를 여러 번 채점했을 때 **평가 대상별 평균**과 흔들린 폭.

    채점자는 실행마다 점수가 달라진다. 한 번의 점수보다 평균과 최저~최고 폭이 그 단계의 실제
    수준을 더 잘 말해 준다.
    """
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_stage.setdefault(str(run.get("stageKey")), []).append(run)

    rows = []
    for items in by_stage.values():
        scores = [item["total"] for item in items if isinstance(item.get("total"), (int, float))]
        latest = max(items, key=lambda item: item.get("judgedAt") or "")
        rows.append(
            {
                "stage": latest.get("label") or latest.get("stageKey"),
                "_num_count": len(items),
                "_num_mean": f"{_mean(scores)}" if scores else "N/A",
                "_num_range": (
                    f"{min(scores):.1f} ~ {max(scores):.1f}" if len(scores) > 1 else "-"
                ),
                "_num_spread": f"{max(scores) - min(scores):.1f}" if len(scores) > 1 else "-",
                "_num_latest": f"{latest['total']}" if isinstance(latest.get("total"), (int, float)) else "N/A",
            }
        )
    rows.sort(key=lambda row: row["stage"])
    return rows


def _render_stage_result(run: dict[str, Any]) -> None:
    """③ 단계 하나의 채점 결과 + 그 단계에 든 대상 실행 비용."""
    usage = run.get("usage") or {}
    columns = st.columns(3)
    columns[0].metric(
        "이 단계 토큰",
        _tokens(usage.get("totalTokens")),
        help="대상 서버가 이 단계에서 쓴 입력+출력 토큰입니다. 점수와는 무관한 기록입니다.",
    )
    columns[1].metric(
        "입력 / 출력", f"{usage.get('inputTokens') or 0:,} / {usage.get('outputTokens') or 0:,}"
    )
    columns[2].metric("이 단계 시간", _seconds(usage.get("durationMs")))
    stage_view.render_scorecard(run.get("scorecard") or {})


def render() -> None:
    st.title("채점 결과")
    st.caption(
        "Task 를 고르고 그 Task 의 채점 실행을 고르면 그때 매긴 결과가 나옵니다. 같은 단계를 다시 "
        "채점해도 이전 기록은 지워지지 않습니다."
    )
    stage_view.inject_css()

    runs = evaluation_record.load_history()
    if not runs:
        st.info("아직 채점 이력이 없습니다. Task 리뷰·채점에서 채점하면 여기에 쌓입니다.")
        return

    envs = env_filter.pick()
    runs = environments.keep(runs, envs)
    if not runs:
        st.info(f"{env_filter.scope_label(envs)}에서 채점한 이력이 없습니다.")
        return

    st.subheader("① Task")
    tasks = task_rows(runs)
    task_event = st.dataframe(
        pd.DataFrame(tasks),
        width="stretch",
        height=min(320, 60 + 36 * len(tasks)),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        # 선택은 행 위치로 돌아오므로 필터가 바뀌면 key 를 바꿔 옛 선택이 다른 Task 를 가리키지 않게 한다.
        key=f"er_tasks_{'-'.join(envs)}",
    )
    picked_task = list(getattr(task_event.selection, "rows", None) or [])
    if not picked_task:
        st.info("Task 를 고르면 그 Task 의 채점 실행 목록이 나타납니다.")
        return
    task = tasks[int(picked_task[0])]
    task_runs = [run for run in runs if str(run.get("taskId")) == task["Task"]]

    st.subheader(f"② 채점 실행 · task {task['Task'][:18]}")
    latest = max(task_runs, key=lambda run: run.get("judgedAt") or "")
    all_scores = [run["total"] for run in task_runs if isinstance(run.get("total"), (int, float))]
    head = st.columns(5)
    head[0].metric("채점 실행", task["채점 실행"])
    head[1].metric(
        "평균 총점",
        f"{_mean(all_scores)}" if all_scores else "-",
        help="이 Task 의 모든 채점 결과를 평균한 값입니다. 채점자는 실행마다 점수가 달라집니다.",
    )
    head[2].metric("Task 전체 토큰", _tokens(latest.get("traceTokens")))
    head[3].metric(
        "Task 전체 시간",
        f"{latest['traceLatency']:.1f}초" if isinstance(latest.get("traceLatency"), (int, float)) else "-",
    )
    head[4].metric(
        "Task 비용",
        f"${latest['traceCost']:.4f}" if isinstance(latest.get("traceCost"), (int, float)) else "-",
        help="LangFuse 가 계산한 트레이스 전체 비용(USD)입니다. 단계별로는 나뉘지 않습니다.",
    )

    st.markdown("**평가 대상별 평균**")
    stage_view.wrapped_table(
        stage_average_rows(task_runs),
        (
            ("stage", "평가 대상", 30),
            ("_num_count", "채점 횟수", 12),
            ("_num_mean", "평균", 12),
            ("_num_latest", "최근", 12),
            ("_num_range", "최저 ~ 최고", 20),
            ("_num_spread", "편차", 14),
        ),
    )

    executions = run_rows(task_runs)
    run_event = st.dataframe(
        pd.DataFrame([{k: v for k, v in row.items() if k != "_items"} for row in executions]),
        width="stretch",
        height=min(300, 60 + 36 * len(executions)),
        hide_index=True,
        column_order=("채점 시각", "채점한 단계", "평균 총점", "직전 실행 대비", "단계별 점수", "기준"),
        on_select="rerun",
        selection_mode="single-row",
        key=f"er_runs_{task['Task']}",
    )
    picked_run = list(getattr(run_event.selection, "rows", None) or [])
    if not picked_run:
        st.info("채점 실행을 고르면 그때 매긴 단계별 점수와 감점 근거가 나타납니다.")
        return
    execution = executions[int(picked_run[0])]

    st.subheader(f"③ 채점 결과 · {execution['채점 시각']}")
    items = sorted(execution["_items"], key=lambda item: item.get("stageKey") or "")
    reference = (items[0].get("rubricRef") or {}) if items else {}
    st.caption(
        f"실행 {execution['runId']} · 기준 {reference.get('name', '-')} "
        f"v{reference.get('version', '-')} · "
        f"{'설정에서 고친 기준' if execution['기준'] == '수정됨' else '메트릭 문서 기본값'}"
    )
    for item in items:
        total = item.get("total")
        with st.expander(
            f"{item.get('label')} · {f'{total}/100' if isinstance(total, (int, float)) else 'N/A'}",
            expanded=len(items) == 1,
        ):
            _render_stage_result(item)
