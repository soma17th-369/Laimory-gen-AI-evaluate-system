"""메트릭 문서 파서와 단계 배점표 — 항목 누락 없이 전달되는지."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.analysis import calibration, metric_doc, stages


class MetricDocumentTests(unittest.TestCase):
    def test_preamble_has_purpose_terms_and_version_differences(self) -> None:
        preamble = metric_doc.preamble()

        self.assertIn("## 문서 목적", preamble)
        self.assertIn("### 판정 용어", preamble)
        self.assertIn("동일 사건", preamble)
        # 버전마다 다른 방식은 채점하지 않는다고 모든 단계 프롬프트 맨 앞에 붙는다.
        self.assertIn("### 버전마다 다른 방식", preamble)
        self.assertIn("### 제품 방침", preamble)
        self.assertNotIn("## 1. 사진 해석", preamble)

    def test_document_is_the_current_metric_version(self) -> None:
        self.assertEqual(metric_doc.METRIC_VERSION, "v6")
        self.assertTrue(metric_doc.DOCUMENT.name.endswith("v6.md"))

    def test_section_includes_children_but_intro_does_not(self) -> None:
        self.assertIn("### 3.2 사건 구성 — 20점", metric_doc.section("3"))
        self.assertNotIn("### 3.1", metric_doc.intro("3"))
        self.assertIn("입력 근거 묶음", metric_doc.intro("3"))

    def test_missing_section_fails_loudly(self) -> None:
        with self.assertRaises(metric_doc.MetricDocumentError):
            metric_doc.section("9.9")


class StageSpecTests(unittest.TestCase):
    def test_seven_targets_each_worth_one_hundred(self) -> None:
        self.assertEqual(
            stages.STAGE_KEYS,
            ("event-photo", "event-notification", "timeline", "repair", "question", "final", "user-memory"),
        )
        for spec in stages.STAGES:
            with self.subTest(stage=spec.key):
                self.assertEqual(spec.total_points, stages.TOTAL_POINTS)

    def test_code_made_sources_are_not_targets(self) -> None:
        """v4 는 위치·일정을 코드가 만든다. 버전을 가로질러 같은 자로 잴 수 없어 단계로 두지 않는다."""
        self.assertNotIn("event-location", stages.STAGE_KEYS)
        self.assertNotIn("event-calendar", stages.STAGE_KEYS)
        self.assertNotIn("event-sleep-activity", stages.STAGE_KEYS)

    def test_item_keys_are_unique_python_identifiers(self) -> None:
        for spec in stages.STAGES:
            keys = [item.key for item in spec.items]
            with self.subTest(stage=spec.key):
                self.assertEqual(len(keys), len(set(keys)))
                for key in keys:
                    self.assertTrue(key.isidentifier(), key)

    def test_user_memory_comes_from_its_own_trace(self) -> None:
        timeline_stages = stages.for_trace(stages.TIMELINE_TRACE)
        memory_stages = stages.for_trace(stages.USER_MEMORY_TRACE)

        self.assertEqual(len(timeline_stages), 6)
        self.assertEqual([spec.key for spec in memory_stages], ["user-memory"])

    def test_rubric_carries_document_text_not_a_summary(self) -> None:
        text = stages.rubric_text(stages.get("timeline"))

        # 공통 머리말, 그 단계의 근거 읽는 법, 항목(키·배점·확인 기준)이 한 덩어리로 들어간다.
        self.assertIn("### 판정 용어", text)
        self.assertIn("## 3. Timeline 초안 — 100점", text)
        self.assertIn("### `composition` · 사건 구성 — 배점 20점", text)
        self.assertIn("같은 동네·비슷한 이름·가까운 거리·이어진 시각만으로 다른 사건을 합치지 않았는가?", text)
        # 배점표를 따로 두지 않는다(배점은 항목 제목에 있다).
        self.assertNotIn("| 항목 키 | 항목 | 배점 |", text)
        # 다른 단계 기준은 섞이지 않는다.
        self.assertNotIn("## 4. Repair", text)
        self.assertNotIn("### 6.1", text)


class ItemCriteriaTests(unittest.TestCase):
    """항목마다 배점과 확인 기준이 붙어야 한다(문서 절을 통째로 붓지 않는다)."""

    def test_every_item_has_criteria(self) -> None:
        for spec in stages.STAGES:
            for entry in stages.criteria(spec):
                with self.subTest(stage=spec.key, item=entry.item.key):
                    self.assertTrue(entry.text.strip(), entry.item.key)

    def test_heading_item_keeps_every_check_line(self) -> None:
        entries = {entry.item.key: entry for entry in stages.criteria(stages.get("timeline"))}
        composition = entries["composition"]

        self.assertEqual(composition.llm.count("- "), 5)
        self.assertEqual(len(calibration.checks(composition.text)), 5)

    def test_question_keeps_the_criteria_order_code_checks_rely_on(self) -> None:
        """deterministic_checks 는 coverage c01·c02 와 expression c02 를 코드로 판정한다."""
        definitions = calibration.definitions(stages.get("question"))

        self.assertEqual(len(definitions["coverage"]), 2)
        self.assertIn("clientEventId", definitions["coverage"][0])
        self.assertIn("40자", definitions["expression"][1])

    def test_table_row_item_splits_llm_and_code_columns(self) -> None:
        """표 한 줄짜리 항목도 같은 모양으로 자른다(문서 형식이 바뀌어도 파서는 그대로 쓴다)."""
        text = (
            "## 문서 목적\n머리말\n## 9. 시험 — 100점\n|측정 기준|LLM 확인|코드 측정|배점|\n|---|---|---|---|\n"
            "|반영|모든 rawId를 포함했는가?|rawId 반영률|100|\n"
        )
        spec = stages.StageSpec(
            "probe", "시험", stages.TIMELINE_TRACE, (), ("9",), (stages.RubricItem("probe", "반영", 100, "|반영|"),)
        )
        with patch.object(metric_doc, "load_text", return_value=text):
            metric_doc._headings.cache_clear()
            try:
                entry = stages.criteria(spec)[0]
            finally:
                metric_doc._headings.cache_clear()

        self.assertEqual(entry.llm, "모든 rawId를 포함했는가?")
        self.assertEqual(entry.code, "rawId 반영률")

    def test_every_stage_passes_validation(self) -> None:
        stages.validate()

    def test_validation_fails_when_document_loses_an_item(self) -> None:
        broken = metric_doc.load_text().replace("### 3.2 사건 구성 — 20점", "### 3.2 사건 구성")

        with patch.object(metric_doc, "load_text", return_value=broken):
            metric_doc.preamble.cache_clear()
            metric_doc._headings.cache_clear()
            try:
                with self.assertRaises(ValueError):
                    stages.validate(stages.get("timeline"))
            finally:
                metric_doc.preamble.cache_clear()
                metric_doc._headings.cache_clear()

    def test_validation_fails_when_an_item_loses_its_criteria(self) -> None:
        text = metric_doc.load_text()
        start = text.index("### 3.7 장소 — 4점")
        end = text.index("### 3.8")
        broken = text[:start] + "### 3.7 장소 — 4점\n" + text[end:]

        with patch.object(metric_doc, "load_text", return_value=broken):
            metric_doc.preamble.cache_clear()
            metric_doc._headings.cache_clear()
            try:
                with self.assertRaises(ValueError):
                    stages.validate(stages.get("timeline"))
            finally:
                metric_doc.preamble.cache_clear()
                metric_doc._headings.cache_clear()


if __name__ == "__main__":
    unittest.main()
