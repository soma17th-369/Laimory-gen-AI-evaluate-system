"""채점 항목 편집 — 설정 화면에서 고친 내용이 그대로 채점 프롬프트로 나가야 한다."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.analysis import rubric_store, stage_judge, stage_schema, stages


class RubricEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        patches = [
            mock.patch.object(rubric_store, "rubric_dir", lambda: root),
            mock.patch.object(rubric_store, "rubric_file", lambda key: root / f"{key}.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _rows(self, **overrides) -> list[dict]:
        rows = [
            {
                "key": entry.item.key,
                "label": entry.item.label,
                "points": entry.item.points,
                "criteria": entry.text,
            }
            for entry in stages.criteria(stages.base("question"))
        ]
        for row in rows:
            if row["key"] in overrides:
                row.update(overrides[row["key"]])
        return rows

    def test_document_default_is_used_until_something_is_saved(self) -> None:
        self.assertFalse(stages.is_edited("question"))
        self.assertIn(
            "회고 유도 조건", [item.label for item in stages.get("question").items]
        )

    def test_saved_items_become_the_scoring_prompt(self) -> None:
        rows = self._rows(
            reflection={"label": "회고 질문다움", "points": 40, "criteria": "- 사용자가 스스로 답을 쓰고 싶어지는가?"},
            expression={"points": 10},
        )

        rubric_store.save("question", rows)

        spec = stages.get("question")
        self.assertTrue(stages.is_edited("question"))
        self.assertEqual(spec.item("reflection").points, 40)
        self.assertEqual(spec.item("reflection").label, "회고 질문다움")
        prompt = stage_judge.system_prompt("question")
        self.assertIn("### `reflection` · 회고 질문다움 — 배점 40점", prompt)
        self.assertIn("사용자가 스스로 답을 쓰고 싶어지는가?", prompt)
        self.assertNotIn("예·아니오만 요구하는 단답형", prompt)  # 문서 원문은 대체됐다

    def test_result_schema_follows_the_edited_items(self) -> None:
        rows = [row for row in self._rows() if row["key"] != "uniqueness"]
        rows[0]["points"] += 10  # 합계 100 유지
        rows.append(
            {"key": "tone", "label": "말투", "points": 0, "criteria": "- 해요체를 지켰는가?"}
        )

        rubric_store.save("question", rows)

        fields = set(stage_schema.items_model("question").model_fields)
        self.assertIn("tone", fields)
        self.assertNotIn("uniqueness", fields)

    def test_totals_must_stay_one_hundred(self) -> None:
        with self.assertRaises(rubric_store.RubricEditError) as error:
            rubric_store.save("question", self._rows(reflection={"points": 40}))

        self.assertIn("110", str(error.exception))
        self.assertFalse(stages.is_edited("question"))

    def test_empty_criteria_is_rejected(self) -> None:
        with self.assertRaises(rubric_store.RubricEditError):
            rubric_store.save("question", self._rows(expression={"criteria": "  "}))

    def test_item_key_must_be_a_usable_field_name(self) -> None:
        with self.assertRaises(rubric_store.RubricEditError):
            rubric_store.save("question", self._rows(expression={"key": "질문 표현"}))

    def test_duplicate_keys_are_rejected(self) -> None:
        with self.assertRaises(rubric_store.RubricEditError):
            rubric_store.save("question", self._rows(expression={"key": "coverage"}))

    def test_reset_goes_back_to_the_document(self) -> None:
        rubric_store.save("question", self._rows(reflection={"criteria": "- 바뀐 기준"}))
        self.assertTrue(stages.is_edited("question"))

        rubric_store.reset("question")

        self.assertFalse(stages.is_edited("question"))
        self.assertIn("예·아니오만 요구하는 단답형", stage_judge.system_prompt("question"))

    def test_editing_one_stage_leaves_the_others_on_the_document(self) -> None:
        rubric_store.save("question", self._rows(reflection={"criteria": "- 바뀐 기준"}))

        self.assertEqual(rubric_store.edited_stages(), {"question"})
        self.assertFalse(stages.is_edited("timeline"))
        self.assertIn("하루 흐름", stage_judge.system_prompt("timeline"))


if __name__ == "__main__":
    unittest.main()
