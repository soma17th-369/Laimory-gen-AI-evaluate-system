from __future__ import annotations

import unittest

from app.ui.evaluation_results import _cell


class EvaluationResultsUiTests(unittest.TestCase):
    def test_table_cell_escapes_html_and_preserves_line_breaks(self) -> None:
        self.assertEqual(_cell("<script>\n근거"), "&lt;script&gt;<br>근거")

    def test_table_cell_renders_missing_value_as_dash(self) -> None:
        self.assertEqual(_cell(None), "-")


if __name__ == "__main__":
    unittest.main()
