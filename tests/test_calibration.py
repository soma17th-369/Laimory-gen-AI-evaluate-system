"""점수 재현성 계약: 같은 판정은 같은 점수, 입력 누락과 출력 누락 구별."""

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.analysis import calibration, stage_judge, stages
from app.analysis.deterministic_checks import confirmed_checks
from app.analysis.evidence import EvidenceSection, StageEvidence


def assessment(total, passed):
    return calibration.CheckAssessment(
        total=total, passed=passed, failedRefs=[f"E{i}" for i in range(total-passed)], reason="검증 근거",
    )


class CalibrationTests(unittest.TestCase):
    def test_fixed_formula_and_na(self):
        cases = [([assessment(5, 5), assessment(5, 5)], (20, True)),
                 ([assessment(5, 4), assessment(5, 5)], (18, True)),
                 ([assessment(5, 4), assessment(0, 0)], (16, True)),
                 ([assessment(5, 0)], (0, True)), ([assessment(0, 0)], (0, False))]
        for rows, expected in cases:
            self.assertEqual(calibration.points_from_checks(20, rows), expected)
        self.assertEqual(calibration.points_from_checks(5, [assessment(2, 1)]), (3, True))

    def test_invalid_counts_and_refs_rejected(self):
        for changes in ({"passed": 2}, {"total": -1}, {"failedRefs": []}, {"reason": " "}, {"total": True}):
            with self.assertRaises(ValidationError):
                calibration.CheckAssessment.model_validate({"total": 1, "passed": 0, "failedRefs": ["E1"], "reason": "r", **changes})

    def test_original_criteria_and_examples_reach_all_eight_live_prompts(self):
        for spec in stages.STAGES:
            prompt = stage_judge.system_prompt(spec.key)
            for entry in stages.criteria(spec):
                self.assertIn(entry.text, prompt)
            self.assertIn("criteria-ratio-v1", prompt)
            self.assertIn("확정 점수", prompt)
            self.assertIn("판정 예시", prompt)
            self.assertEqual(spec.total_points, 100)

    def test_subcriteria_are_fixed_including_nested_and_table(self):
        self.assertEqual(len(calibration.definitions(stages.get("question"))["reflection"]), 5)
        self.assertEqual(len(calibration.definitions(stages.get("user-memory"))["field_placement"]), 10)
        merged = calibration.definitions(stages.get("timeline"))["event_merge"]
        self.assertEqual(len(merged), 9)
        self.assertIn("서로 시간 범위가 겹쳐야 한다", merged[0])
        self.assertNotIn("코드 측정", "\n".join(calibration.definitions(stages.get("timeline"))["source_final"]))

    def test_live_schema_rejects_missing_or_extra_criterion(self):
        spec = stages.get("question")
        model = calibration.result_model(spec)
        payload = self.payload(spec)
        model.model_validate(payload)
        del payload["items"]["reflection"]["c01"]
        with self.assertRaises(ValidationError):
            model.model_validate(payload)
        payload = self.payload(spec)
        payload["items"]["reflection"]["c99"] = assessment(1, 1).model_dump()
        with self.assertRaises(ValidationError):
            model.model_validate(payload)

    @staticmethod
    def payload(spec):
        return {"items": {
            key: {f"c{i:02}": assessment(1, 1).model_dump() for i in range(1, len(texts)+1)}
            for key, texts in calibration.definitions(spec).items()
        }, "deductions": [], "alerts": [], "summary": "합성 검증"}

    def test_new_assessments_produce_old_display_shape_and_audit_fields(self):
        spec = stages.get("question")
        payload = self.payload(spec)
        payload["items"]["reflection"]["c03"] = assessment(1, 0).model_dump()
        card = calibration.result_model(spec).model_validate(payload)
        result = calibration.score(spec, card).to_dict()
        self.assertEqual(result["total"], 94)
        self.assertEqual(next(row["score"] for row in result["items"] if row["key"] == "reflection"), 24)
        self.assertEqual(result["scoringPolicy"], calibration.POLICY_VERSION)
        self.assertIn("c03", result["checks"]["reflection"])
        from app.analysis.evaluation_record import to_stage_scores
        restored = to_stage_scores({"stages": {"question": {"scorecard": result}}})[0].to_dict()
        self.assertEqual(restored["checks"], result["checks"])
        self.assertEqual(restored["scoringPolicy"], result["scoringPolicy"])

    def test_edited_rubric_controls_schema_without_stale_domain_examples(self):
        edited = [{"key": "custom", "label": "사용자 기준", "points": 100, "criteria": "- 첫 조건\n- 둘째 조건"}]
        with patch("app.analysis.rubric_store.load", return_value=edited), patch.object(stages, "is_edited", return_value=True):
            spec = stages.get("question")
            model = calibration.result_model(spec)
            self.assertEqual(set(model.model_fields["items"].annotation.model_fields), {"custom"})
            prompt = stage_judge.system_prompt("question")
            self.assertIn("c02: 둘째 조건", prompt)
            self.assertNotIn("공원 산책", prompt)

    def test_deterministic_results_override_model_counts_in_actual_judge(self):
        spec = stages.get("question")
        ev = question_evidence([{"clientEventId": "E1"}], [])
        card = calibration.result_model(spec).model_validate(self.payload(spec))
        with patch.object(stage_judge, "get_llm_provider") as provider:
            provider.return_value.evaluate.return_value = card
            result = stage_judge.score_evidence(ev)
        self.assertEqual(next(row.score for row in result.items if row.key == "coverage"), 0)
        self.assertIn("확정 판정", provider.return_value.evaluate.call_args.kwargs["user_prompt"])


def question_evidence(inputs, outputs):
    return StageEvidence(stages.get("question"), True, sections=(
        EvidenceSection("입력 event", "", inputs), EvidenceSection("출력 질문", "", outputs),
    ))


class DeterministicTests(unittest.TestCase):
    def test_missing_duplicate_unknown_ids_and_empty_questions(self):
        inputs = [{"clientEventId": f"E{i}"} for i in range(1, 6)]
        outputs = [{"clientEventId": "E1", "question": "질문?"},
                   {"clientEventId": "E2", "question": "질문?"},
                   {"clientEventId": "E2", "question": "중복?"},
                   {"clientEventId": "E3", "question": " "},
                   {"clientEventId": "UNKNOWN", "question": "질문?"}]
        result = confirmed_checks(question_evidence(inputs, outputs))
        self.assertEqual(result["coverage"]["c01"]["passed"], 1)
        self.assertEqual(result["coverage"]["c01"]["failedRefs"], ["E2", "E3", "E4", "E5"])

    def test_length_boundary_and_missing_output(self):
        inputs = [{"clientEventId": "E1"}, {"clientEventId": "E2"}, {"clientEventId": "E3"}]
        outputs = [{"clientEventId": "E1", "question": " " + "가"*40 + " "},
                   {"clientEventId": "E2", "question": "가"*41}]
        result = confirmed_checks(question_evidence(inputs, outputs))["expression"]["c02"]
        self.assertEqual((result["total"], result["passed"]), (3, 1))
        result = confirmed_checks(question_evidence(inputs, []))["coverage"]["c01"]
        self.assertEqual((result["total"], result["passed"]), (3, 0))

    def test_invalid_input_and_edited_rubric_not_overridden(self):
        self.assertEqual(confirmed_checks(question_evidence("not json", [])), {})
        with patch.object(stages, "is_edited", return_value=True):
            self.assertEqual(confirmed_checks(question_evidence([], [])), {})


if __name__ == "__main__":
    unittest.main()
