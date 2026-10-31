"""메트릭 문서 파서와 단계 배점표 — 항목 누락 없이 전달되는지."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.analysis import metric_doc, stages


class MetricDocumentTests(unittest.TestCase):
    def test_preamble_has_purpose_and_terms(self) -> None:
        preamble = metric_doc.preamble()

        self.assertIn("## 문서 목적", preamble)
        self.assertIn("### 판정 용어", preamble)
        self.assertIn("동일 사건", preamble)
        self.assertNotIn("## 1. Event Agent", preamble)

    def test_section_includes_children_but_intro_does_not(self) -> None:
        self.assertIn("#### 이동 흐름 — 20점", metric_doc.section("1.2"))
        self.assertIn("### 1.2 Location Agent — 80점", metric_doc.section("1"))
        self.assertNotIn("### 1.1 공통 기준", metric_doc.intro("1"))
        self.assertIn("공통 기준 20점과 해당 source Agent 기준 80점", metric_doc.intro("1"))

    def test_missing_section_fails_loudly(self) -> None:
        with self.assertRaises(metric_doc.MetricDocumentError):
            metric_doc.section("9.9")


class StageSpecTests(unittest.TestCase):
    def test_eight_targets_each_worth_one_hundred(self) -> None:
        self.assertEqual(len(stages.STAGES), 8)
        for spec in stages.STAGES:
            with self.subTest(stage=spec.key):
                self.assertEqual(spec.total_points, stages.TOTAL_POINTS)

    def test_item_keys_are_unique_python_identifiers(self) -> None:
        for spec in stages.STAGES:
            keys = [item.key for item in spec.items]
            with self.subTest(stage=spec.key):
                self.assertEqual(len(keys), len(set(keys)))
                for key in keys:
                    self.assertTrue(key.isidentifier(), key)

    def test_sleep_activity_is_not_a_target(self) -> None:
        self.assertNotIn("event-sleep-activity", stages.STAGE_KEYS)

    def test_user_memory_comes_from_its_own_trace(self) -> None:
        timeline_stages = stages.for_trace(stages.TIMELINE_TRACE)
        memory_stages = stages.for_trace(stages.USER_MEMORY_TRACE)

        self.assertEqual(len(timeline_stages), 7)
        self.assertEqual([spec.key for spec in memory_stages], ["user-memory"])

    def test_rubric_carries_document_text_not_a_summary(self) -> None:
        text = stages.rubric_text(stages.get("event-location"))

        # 공통 머리말과 항목(키·배점·확인 기준)이 한 덩어리로 들어간다.
        self.assertIn("### 판정 용어", text)
        self.assertIn("### `movement_flow` · 이동 흐름 — 배점 20점", text)
        self.assertIn("장거리 이동은 출발지와 최종 도착지를 중심으로 표현했는가?", text)
        # 배점표를 따로 두지 않는다(배점은 항목 제목에 있다).
        self.assertNotIn("| 항목 키 | 항목 | 배점 |", text)
        # 코드 측정은 채점에 쓰지 않으므로 프롬프트에 넣지 않는다.
        self.assertNotIn("코드 측정:", text)
        self.assertNotIn("MOVEMENT rawId 반영률", text)
        self.assertNotIn("- `코드 측정`:", text)
        self.assertNotIn("## 6. 점수 작성 형식", text)
        # 다른 Agent 기준은 섞이지 않는다.
        self.assertNotIn("### 1.4 Notification Agent", text)
        self.assertNotIn("메신저 기반 SOCIAL candidate", text)


class ItemCriteriaTests(unittest.TestCase):
    """항목마다 배점과 확인 기준이 붙어야 한다(문서 절을 통째로 붓지 않는다)."""

    def test_every_item_has_criteria(self) -> None:
        for spec in stages.STAGES:
            for entry in stages.criteria(spec):
                with self.subTest(stage=spec.key, item=entry.item.key):
                    self.assertTrue(entry.text.strip(), entry.item.key)

    def test_table_row_item_splits_llm_and_code_columns(self) -> None:
        entries = {entry.item.key: entry for entry in stages.criteria(stages.get("event-calendar"))}

        schedule = entries["schedule_coverage"]
        self.assertEqual(schedule.llm, "모든 Calendar rawId를 candidate·fragment에 포함했는가?")
        self.assertEqual(schedule.code, "Calendar rawId 반영률과 누락 수")

    def test_marker_inside_a_table_row_still_finds_its_row(self) -> None:
        """표 항목의 marker 는 줄 가운데(LLM 확인 칸)에 있을 수 있다."""
        entries = {entry.item.key: entry for entry in stages.criteria(stages.get("event-calendar"))}

        self.assertIn("입력에 참석자가 있으면", entries["required_fields"].llm)

    def test_heading_item_keeps_every_check_line(self) -> None:
        entries = {entry.item.key: entry for entry in stages.criteria(stages.get("event-location"))}
        stay = entries["stay_merge"]

        self.assertEqual(stay.llm.count("\n- "), 3)  # 확인 질문 4줄
        self.assertIn("동일 rawId 중복 사용 수", stay.code)

    def test_item_without_an_llm_label_keeps_its_table_as_criteria(self) -> None:
        """5.3 은 `LLM 확인` 라벨 없이 설명 문장과 고정 field 표로 기준을 적는다."""
        entries = {entry.item.key: entry for entry in stages.criteria(stages.get("user-memory"))}
        placement = entries["field_placement"]

        self.assertIn("user memory 고정 필드", placement.llm)
        self.assertIn("`basicProfile`", placement.llm)
        self.assertNotIn("근거 일치율", placement.llm)  # 코드 측정은 따로 간다
        self.assertIn("근거 일치율", placement.code)

    def test_validation_fails_when_an_item_loses_its_criteria(self) -> None:
        broken = metric_doc.load_text().replace(
            "|출력 형식|지정된 JSON 구조와 필드 의미를 지켰는가?|JSON parse, Pydantic schema 통과 여부|5|",
            "|출력 형식|||5|",
        )

        with patch.object(metric_doc, "load_text", return_value=broken):
            metric_doc.preamble.cache_clear()
            metric_doc._headings.cache_clear()
            try:
                with self.assertRaises(ValueError):
                    stages.validate(stages.get("event-calendar"))
            finally:
                metric_doc.preamble.cache_clear()
                metric_doc._headings.cache_clear()

    def test_every_stage_passes_validation(self) -> None:
        stages.validate()

    def test_validation_fails_when_document_loses_an_item(self) -> None:
        broken = metric_doc.load_text().replace("#### 이동 흐름 — 20점", "#### 이동 흐름")

        with patch.object(metric_doc, "load_text", return_value=broken):
            metric_doc.preamble.cache_clear()
            metric_doc._headings.cache_clear()
            try:
                with self.assertRaises(ValueError):
                    stages.validate(stages.get("event-location"))
            finally:
                metric_doc.preamble.cache_clear()
                metric_doc._headings.cache_clear()


if __name__ == "__main__":
    unittest.main()
