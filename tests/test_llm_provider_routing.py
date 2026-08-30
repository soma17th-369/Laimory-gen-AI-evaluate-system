from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from app.improve import suggest as prompt_suggest
from app.improve.schema import PromptReview
from app.testdata import generate as testdata_generate
from app.testdata.schema import TestSuite
from app.ui import improvement as improvement_ui
from app.ui import testdata as testdata_ui


def _scorecard() -> SimpleNamespace:
    return SimpleNamespace(
        overall=SimpleNamespace(score=8),
        summary="종합 평가",
        findings=[],
    )


class LlmProviderRoutingTests(unittest.TestCase):
    def test_prompt_suggestions_use_common_structured_provider(self) -> None:
        expected = PromptReview(suggestions=[], summary="개선 요약")
        provider = mock.Mock()
        provider.generate_structured.return_value = expected

        with mock.patch.object(prompt_suggest, "get_llm_provider", return_value=provider):
            result = prompt_suggest.suggest_prompt_improvements(
                SimpleNamespace(observations=[]),
                _scorecard(),
            )

        self.assertIs(result, expected)
        self.assertIs(
            provider.generate_structured.call_args.kwargs["result_model"],
            PromptReview,
        )

    def test_scorecard_test_cases_use_common_structured_provider(self) -> None:
        expected = TestSuite(cases=[], summary="테스트 요약")
        provider = mock.Mock()
        provider.generate_structured.return_value = expected

        with mock.patch.object(testdata_generate, "get_llm_provider", return_value=provider):
            result = testdata_generate.generate_test_cases(_scorecard())

        self.assertIs(result, expected)
        self.assertIs(
            provider.generate_structured.call_args.kwargs["result_model"],
            TestSuite,
        )

    def test_improvement_body_uses_common_text_provider(self) -> None:
        provider = mock.Mock()
        provider.generate_text.return_value = "개선책 본문"
        evaluations = [
            {
                "taskId": "task-1",
                "scorecard": {"overall": {"score": 8}, "findings": []},
            }
        ]

        with mock.patch.object(improvement_ui, "get_llm_provider", return_value=provider):
            result = improvement_ui._generate(evaluations, "작성 지시")

        self.assertEqual(result, "개선책 본문")
        self.assertEqual(
            provider.generate_text.call_args.kwargs["system_prompt"],
            "작성 지시",
        )
        self.assertIn("task-1", provider.generate_text.call_args.kwargs["user_prompt"])

    def test_improvement_test_cases_use_common_structured_provider(self) -> None:
        expected = TestSuite(cases=[], summary="검증 요약")
        provider = mock.Mock()
        provider.generate_structured.return_value = expected

        with mock.patch.object(testdata_ui, "get_llm_provider", return_value=provider):
            result = testdata_ui._gen_from_improvement("개선 계획")

        self.assertIs(result, expected)
        self.assertIs(
            provider.generate_structured.call_args.kwargs["result_model"],
            TestSuite,
        )


if __name__ == "__main__":
    unittest.main()
