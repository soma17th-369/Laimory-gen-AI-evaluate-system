"""Task 리뷰 목록 — 표에서 고른 행을 그대로 상세로 잇는 부분."""

from __future__ import annotations

import unittest

from streamlit.util import ReadOnlyAttributeDictionary

from app.ui.task_review import _picked_row, _selectable_rows


def _selection(rows: list[int]) -> ReadOnlyAttributeDictionary:
    """`st.dataframe(on_select=...)` 가 돌려주는 선택 상태 흉내."""
    return ReadOnlyAttributeDictionary({"rows": rows, "columns": [], "cells": []})


class SelectableRowsTests(unittest.TestCase):
    def test_rows_without_a_trace_id_are_dropped(self) -> None:
        rows = _selectable_rows([{"id": "t1"}, {"id": None}, {}, "not a dict"])

        self.assertEqual(rows, [{"id": "t1"}])

    def test_rows_are_copied_so_the_table_cannot_mutate_the_snapshot(self) -> None:
        source = [{"id": "t1", "name": "main-agent"}]

        rows = _selectable_rows(source)
        rows[0]["name"] = "바뀜"

        self.assertEqual(source[0]["name"], "main-agent")

    def test_order_is_preserved(self) -> None:
        """선택은 표의 위치 index 로 오므로 넘긴 순서가 그대로 유지돼야 한다."""
        rows = _selectable_rows([{"id": "t1"}, {"id": "t2"}, {"id": "t3"}])

        self.assertEqual([row["id"] for row in rows], ["t1", "t2", "t3"])


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
