"""채점 결과 페이지 — Task → 채점 실행 → 단계 흐름과 공용 렌더러."""

from __future__ import annotations

import unittest

from app.ui.evaluation_results import run_rows, stage_average_rows, task_rows
from app.ui.stage_view import _cell, source_status


def _run(
    judged: str,
    stage: str,
    total: float | None,
    *,
    task: str = "task-1",
    run_id: str = "run-1",
    deductions: int = 0,
) -> dict:
    return {
        "runId": run_id,
        "judgedAt": judged,
        "taskId": task,
        "date": "2026-09-04",
        "env": "dev",
        "stageKey": stage,
        "label": f"{stage} Agent",
        "total": total,
        "rubricEdited": False,
        "traceTokens": 81876,
        "traceCost": 0.0655,
        "traceLatency": 44.2,
        "usage": {"totalTokens": 10827, "inputTokens": 9193, "outputTokens": 1634, "durationMs": 6554.7},
        "scorecard": {"total": total, "deductions": [{}] * deductions, "alerts": []},
    }


class TaskRowTests(unittest.TestCase):
    """① Task 하나에 채점 실행이 몇 번 쌓였는지가 먼저 보여야 한다."""

    def test_runs_are_grouped_per_task(self) -> None:
        rows = task_rows(
            [
                _run("2026-09-06T23:00:00", "timeline", 58.9, run_id="run-1"),
                _run("2026-09-07T01:00:00", "timeline", 54.7, run_id="run-2"),
                _run("2026-09-07T01:00:00", "repair", 32.0, run_id="run-2"),
                _run("2026-09-07T02:00:00", "timeline", 90.0, task="task-2", run_id="run-3"),
            ]
        )

        by_task = {row["Task"]: row for row in rows}
        self.assertEqual(by_task["task-1"]["채점 실행"], 2)
        self.assertEqual(by_task["task-1"]["채점 건수"], 3)
        self.assertEqual(by_task["task-1"]["평균 총점"], "48.5")
        self.assertEqual(by_task["task-1"]["마지막 채점"], "2026-09-07 01:00")

    def test_task_level_cost_comes_from_the_latest_run(self) -> None:
        rows = task_rows([_run("2026-09-07T01:00:00", "timeline", 54.7)])

        self.assertEqual(rows[0]["Task 토큰"], "81,876")
        self.assertEqual(rows[0]["Task 비용"], "$0.0655")

    def test_newest_task_comes_first(self) -> None:
        rows = task_rows(
            [
                _run("2026-09-05T01:00:00", "timeline", 50.0, task="old"),
                _run("2026-09-07T01:00:00", "timeline", 50.0, task="new"),
            ]
        )

        self.assertEqual([row["Task"] for row in rows], ["new", "old"])


class RunRowTests(unittest.TestCase):
    """② 한 줄이 채점 한 번. 여러 단계를 함께 채점했으면 한 줄로 묶인다."""

    def test_stages_scored_together_are_one_row(self) -> None:
        rows = run_rows(
            [
                _run("2026-09-07T01:00:00", "timeline", 54.7, run_id="run-2"),
                _run("2026-09-07T01:00:00", "repair", 32.0, run_id="run-2"),
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["채점한 단계"], 2)
        self.assertEqual(rows[0]["평균 총점"], "43.4")
        self.assertIn("repair Agent 32.0", rows[0]["단계별 점수"])

    def test_runs_are_newest_first_with_gap_from_the_previous_run(self) -> None:
        rows = run_rows(
            [
                _run("2026-09-06T23:00:00", "timeline", 58.9, run_id="run-1"),
                _run("2026-09-07T01:00:00", "timeline", 54.7, run_id="run-2"),
            ]
        )

        self.assertEqual([row["채점 시각"] for row in rows], ["2026-09-07 01:00", "2026-09-06 23:00"])
        self.assertEqual(rows[0]["직전 실행 대비"], "-4.2")
        self.assertEqual(rows[1]["직전 실행 대비"], "")

    def test_unscored_stage_does_not_break_the_average(self) -> None:
        rows = run_rows(
            [
                _run("2026-09-07T01:00:00", "event-photo", None, run_id="run-2"),
                _run("2026-09-07T01:00:00", "timeline", 54.7, run_id="run-2"),
            ]
        )

        self.assertEqual(rows[0]["평균 총점"], "54.7")
        self.assertEqual(rows[0]["채점한 단계"], 2)

    def test_run_keeps_its_stage_records_for_the_detail_view(self) -> None:
        rows = run_rows([_run("2026-09-07T01:00:00", "timeline", 54.7)])

        self.assertEqual(len(rows[0]["_items"]), 1)
        self.assertEqual(rows[0]["_items"][0]["usage"]["totalTokens"], 10827)


class StageAverageTests(unittest.TestCase):
    """Task 를 여러 번 채점했으면 평균과 흔들린 폭이 보여야 한다."""

    def test_average_and_spread_per_stage(self) -> None:
        rows = stage_average_rows(
            [
                _run("2026-09-06T23:00:00", "repair", 44.0, run_id="run-1"),
                _run("2026-09-07T01:00:00", "repair", 32.0, run_id="run-2"),
                _run("2026-09-07T01:00:00", "question", 100.0, run_id="run-2"),
            ]
        )

        by_stage = {row["stage"]: row for row in rows}
        repair = by_stage["repair Agent"]
        self.assertEqual(repair["_num_count"], 2)
        self.assertEqual(repair["_num_mean"], "38.0")
        self.assertEqual(repair["_num_latest"], "32.0")
        self.assertEqual(repair["_num_range"], "32.0 ~ 44.0")
        self.assertEqual(repair["_num_spread"], "12.0")

    def test_single_run_has_no_range(self) -> None:
        rows = stage_average_rows([_run("2026-09-07T01:00:00", "timeline", 54.7)])

        self.assertEqual(rows[0]["_num_mean"], "54.7")
        self.assertEqual(rows[0]["_num_range"], "-")
        self.assertEqual(rows[0]["_num_spread"], "-")

    def test_unscored_stage_reports_na_without_breaking(self) -> None:
        rows = stage_average_rows([_run("2026-09-07T01:00:00", "event-photo", None)])

        self.assertEqual(rows[0]["_num_mean"], "N/A")
        self.assertEqual(rows[0]["_num_latest"], "N/A")


class TableCellTests(unittest.TestCase):
    def test_table_cell_escapes_html_and_preserves_line_breaks(self) -> None:
        self.assertEqual(_cell("<script>\n근거"), "&lt;script&gt;<br>근거")

    def test_table_cell_renders_missing_value_as_dash(self) -> None:
        self.assertEqual(_cell(None), "-")


class SourceStatusTests(unittest.TestCase):
    def test_counts_and_user_memory_state_are_read_from_the_trace(self) -> None:
        status = source_status(
            {
                "task": {"window": {"start": "s", "end": "e"}, "traceName": "generate-timeline"},
                "source": {
                    "date": "2026-09-04",
                    "timezone": "Asia/Seoul",
                    "stays": [{}, {}],
                    "notifications": [{}],
                    "userMemory": {"contentCaptured": False, "filledFieldCount": 1},
                },
                "operation": {"status": "SUCCESS"},
            }
        )

        self.assertEqual(status["counts"]["stays"], 2)
        self.assertEqual(status["counts"]["photos"], 0)
        self.assertFalse(status["userMemory"]["captured"])
        self.assertEqual(status["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
