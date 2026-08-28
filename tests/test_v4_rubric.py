from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.analysis.judge import _clamp_scores, assemble_evidence, find_final_timeline
from app.analysis.rubric import SYSTEM_PROMPT, build_user_prompt
from app.analysis.schema import CRITERION_KEYS, METRIC_KEYS, Finding, TraceScorecard
from app.prompts import registry


class V4RubricTests(unittest.TestCase):
    def test_v4_composes_v2_and_v3_without_changing_sources(self) -> None:
        v2 = registry.get("judge-rubric", 2)
        v3 = registry.get("judge-rubric", 3)
        v4 = registry.get("judge-rubric", 4)

        self.assertIsNotNone(v2)
        self.assertIsNotNone(v3)
        self.assertIsNotNone(v4)
        self.assertEqual(v4["parts"], [2, 3])
        self.assertIn(v2["content"], v4["content"])
        self.assertIn(v3["content"], v4["content"])
        self.assertEqual(SYSTEM_PROMPT, v4["content"])

    def test_schema_has_seven_scores_and_twenty_metrics(self) -> None:
        schema = TraceScorecard.model_json_schema()

        self.assertEqual(len(CRITERION_KEYS), 7)
        self.assertIn("composition", CRITERION_KEYS)
        self.assertEqual(len(METRIC_KEYS), 20)
        self.assertIn("metrics", schema["required"])

    def test_legacy_med_severity_is_normalized(self) -> None:
        finding = Finding(criterion="writing", severity="MED", description="문장 문제")
        self.assertEqual(finding.severity, "MEDIUM")

    def test_empty_event_timeline_is_still_final_output(self) -> None:
        timeline = {"events": [], "questions": [], "warnings": ["근거 부족"]}
        observation = SimpleNamespace(name="main-agent", output={"timeline": timeline})
        trace = SimpleNamespace(observations=[observation])
        self.assertEqual(find_final_timeline(trace), timeline)

    def test_input_prompt_uses_complete_canonical_sources(self) -> None:
        long_marker = "사진근거" * 8000
        timeline = {"events": [], "questions": [], "warnings": []}
        observation = SimpleNamespace(
            name="main-agent",
            type="SPAN",
            output={"timeline": timeline},
        )
        trace = SimpleNamespace(
            name="generate-timeline",
            input={
                "taskId": "task-1",
                "window": {"start": "2026-08-08T00:00:00+09:00", "end": "2026-08-09T00:00:00+09:00"},
                "request": {
                    "date": "2026-08-08",
                    "timezone": "Asia/Seoul",
                    "photos": [{"rawId": "photo-1", "description": long_marker}],
                },
            },
            output={"status": "COMPLETED"},
            observations=[observation],
        )

        prompt = build_user_prompt(assemble_evidence(trace))

        self.assertIn(long_marker, prompt)
        self.assertIn('"rawId": "photo-1"', prompt)
        self.assertIn("v3의 20개 Metric", prompt)
        self.assertNotIn("…(생략:", prompt)

    def test_metric_ranges_and_zero_denominator_are_normalized(self) -> None:
        metric = {"value": 50, "numerator": 1, "denominator": 2, "reason": "계산"}
        data = {
            "scores": {
                key: {"score": 8, "reason": "근거"}
                for key in CRITERION_KEYS
            },
            "metrics": {key: dict(metric) for key in METRIC_KEYS},
            "overall": {"score": 8, "reason": "종합"},
            "findings": [],
            "summary": "요약",
        }
        data["metrics"]["groundedEventPrecision"] = {
            "value": 130,
            "numerator": 13,
            "denominator": 10,
            "reason": "범위 초과",
        }
        data["metrics"]["meanTemporalIoU"] = {
            "value": 1.23456,
            "numerator": 1.23456,
            "denominator": 1,
            "reason": "IoU",
        }
        data["metrics"]["photoAssignmentRate"] = {
            "value": 100,
            "numerator": 0,
            "denominator": 0,
            "reason": "사진 없음",
        }

        card = _clamp_scores(TraceScorecard.model_validate(data))

        self.assertEqual(card.metrics.groundedEventPrecision.value, 100.0)
        self.assertEqual(card.metrics.meanTemporalIoU.value, 1.0)
        self.assertIsNone(card.metrics.photoAssignmentRate.value)
        self.assertIsNone(card.metrics.photoAssignmentRate.denominator)


if __name__ == "__main__":
    unittest.main()
