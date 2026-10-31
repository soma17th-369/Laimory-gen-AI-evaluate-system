"""Task 리뷰 목록 — 표에서 고른 행을 그대로 상세로 잇는 부분."""

from __future__ import annotations

import unittest

from streamlit.util import ReadOnlyAttributeDictionary

from app.ui.task_review import _is_scorable, _picked_row, _selectable_rows, display_rows


def _selection(rows: list[int]) -> ReadOnlyAttributeDictionary:
    """`st.dataframe(on_select=...)` 가 돌려주는 선택 상태 흉내."""
    return ReadOnlyAttributeDictionary({"rows": rows, "columns": [], "cells": []})


class SelectableRowsTests(unittest.TestCase):
    def test_rows_without_a_trace_id_are_dropped(self) -> None:
        rows = _selectable_rows([{"id": "t1"}, {"id": None}, {}, "not a dict"], only_scorable=False)

        self.assertEqual(rows, [{"id": "t1"}])

    def test_rows_are_copied_so_the_table_cannot_mutate_the_snapshot(self) -> None:
        source = [{"id": "t1", "name": "main-agent"}]

        rows = _selectable_rows(source, only_scorable=False)
        rows[0]["name"] = "바뀜"

        self.assertEqual(source[0]["name"], "main-agent")

    def test_order_is_preserved(self) -> None:
        """선택은 표의 위치 index 로 오므로 넘긴 순서가 그대로 유지돼야 한다."""
        rows = _selectable_rows([{"id": "t1"}, {"id": "t2"}, {"id": "t3"}], only_scorable=False)

        self.assertEqual([row["id"] for row in rows], ["t1", "t2", "t3"])


class ScorableFilterTests(unittest.TestCase):
    """수집 목록의 99%는 대상 서버 테스트 실행이라 채점 대상만 남겨야 한다."""

    def test_real_timeline_and_user_memory_runs_are_scorable(self) -> None:
        for name in ("generate-timeline", "update-user-memory"):
            with self.subTest(name=name):
                self.assertTrue(
                    _is_scorable({"name": name, "taskId": "01a0413d-1e34-7785-b1dc-5e8bc5321f02"})
                )

    def test_test_runs_and_fragment_traces_are_dropped(self) -> None:
        self.assertFalse(_is_scorable({"name": "generate-timeline", "taskId": "task-test"}))
        self.assertFalse(_is_scorable({"name": "main-agent", "taskId": "task-test"}))
        self.assertFalse(
            _is_scorable({"name": "call-llm", "taskId": "01a0413d-1e34-7785-b1dc-5e8bc5321f02"})
        )
        self.assertFalse(_is_scorable({"name": "generate-timeline", "taskId": None}))

    def test_filter_keeps_list_order(self) -> None:
        rows = [
            {"id": "t1", "name": "call-llm", "taskId": "task-test"},
            {"id": "t2", "name": "generate-timeline", "taskId": "01a0413d-1e34-7785-b1dc-5e8bc5321f02"},
            {"id": "t3", "name": "generate-timeline", "taskId": "01a075be-f239-7f18-b2f9-8c1f82d8d0e0"},
        ]

        self.assertEqual(
            [row["id"] for row in _selectable_rows(rows, only_scorable=True)], ["t2", "t3"]
        )
        self.assertEqual(len(_selectable_rows(rows, only_scorable=False)), 3)


class ScoredColumnTests(unittest.TestCase):
    """목록만 보고 어느 Task 를 채점했는지 알 수 있어야 한다(O/X)."""

    def _rows(self, scored: dict) -> list[dict]:
        rows = [
            {"id": "t1", "name": "generate-timeline", "taskId": "task-done"},
            {"id": "t2", "name": "generate-timeline", "taskId": "task-none"},
            {"id": "t3", "name": "generate-timeline", "taskId": "task-old"},
        ]
        return _selectable_rows(rows, only_scorable=False, scored=scored)

    def test_scored_task_is_marked_o_with_the_time(self) -> None:
        scored = {
            "task-done": {
                "schemaVersion": 2,
                "composite": {"score": 63.4, "evaluatedCount": 4},
                "updatedAt": "2026-09-07T02:21:00+09:00",
            }
        }

        row = self._rows(scored)[0]

        self.assertEqual(row["채점 여부"], "O")
        self.assertEqual(row["채점 시각"], "2026-09-07 02:21")

    def test_unscored_and_legacy_are_both_x(self) -> None:
        scored = {"task-old": {"taskId": "task-old", "scorecard": {"overall": {"score": 7}}}}

        rows = self._rows(scored)

        self.assertEqual(rows[1]["채점 여부"], "X")
        self.assertEqual(rows[2]["채점 여부"], "X")
        self.assertEqual(rows[2]["채점 시각"], "")

    def test_record_without_a_scored_stage_is_x(self) -> None:
        scored = {"task-done": {"schemaVersion": 2, "composite": {"evaluatedCount": 0}}}

        self.assertEqual(self._rows(scored)[0]["채점 여부"], "X")


class DisplayRowTests(unittest.TestCase):
    """표에는 정해진 열만, 단위를 붙여 내보낸다."""

    def test_units_are_attached_and_extra_columns_dropped(self) -> None:
        rows = display_rows(
            [
                {
                    "id": "trace-1",
                    "user_id": None,
                    "env": "dev",
                    "timestamp": "2026-08-27 03:22:00.453000+00:00",
                    "taskId": "01a0413d-1e34-7785-b1dc-5e8bc5321f02",
                    "name": "generate-timeline",
                    "latency": 44.206,
                    "total_cost": 0.0655467,
                    "채점 여부": "O",
                    "채점 시각": "2026-09-07 02:21",
                }
            ]
        )

        self.assertEqual(
            list(rows[0]),
            ["env", "timestamp", "taskId", "task", "task_time", "total_cost", "채점 여부", "채점 시각"],
        )
        self.assertEqual(rows[0]["task"], "generate-timeline")
        self.assertEqual(rows[0]["task_time"], "44.2s")
        self.assertEqual(rows[0]["total_cost"], "$0.0655")
        self.assertEqual(rows[0]["timestamp"], "2026-08-27 03:22:00")

    def test_missing_latency_and_cost_stay_empty(self) -> None:
        rows = display_rows([{"id": "t", "name": "generate-timeline", "taskId": "task-1"}])

        self.assertEqual(rows[0]["task_time"], "")
        self.assertEqual(rows[0]["total_cost"], "")
        self.assertEqual(rows[0]["채점 여부"], "X")


class PickedRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]

    def test_selected_position_maps_back_to_that_row(self) -> None:
        self.assertEqual(_picked_row(self.rows, _selection([1])), {"id": "t2"})

    def test_nothing_selected_gives_nothing(self) -> None:
        self.assertIsNone(_picked_row(self.rows, _selection([])))

    def test_out_of_range_position_is_ignored(self) -> None:
        """행이 줄어든 뒤의 오래된 선택이 IndexError 로 페이지를 깨뜨리지 않는다."""
        self.assertIsNone(_picked_row(self.rows, _selection([9])))
        self.assertIsNone(_picked_row(self.rows, _selection([-1])))

    def test_selection_object_without_rows_is_treated_as_empty(self) -> None:
        self.assertIsNone(_picked_row(self.rows, ReadOnlyAttributeDictionary({})))


if __name__ == "__main__":
    unittest.main()
