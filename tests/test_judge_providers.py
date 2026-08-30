from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.analysis.providers import (
    CodexProvider,
    CodexExecutionFailed,
    CodexJudgeProvider,
    CodexNotAuthenticated,
    CodexNotInstalled,
    CodexTimeout,
    InvalidJudgeOutput,
    JudgeSchemaValidationFailed,
    OpenAIApiProvider,
    OpenAIApiJudgeProvider,
    _strict_json_schema,
    get_judge_provider,
    get_llm_provider,
)
from app.analysis.schema import CRITERION_KEYS, METRIC_KEYS, TraceScorecard
from app.config import Settings


def _scorecard_data() -> dict:
    metric = {"value": 50, "numerator": 1, "denominator": 2, "reason": "계산 근거"}
    return {
        "scores": {key: {"score": 8, "reason": "점수 근거"} for key in CRITERION_KEYS},
        "metrics": {key: dict(metric) for key in METRIC_KEYS},
        "overall": {"score": 8, "reason": "종합 근거"},
        "findings": [],
        "summary": "종합 평가",
    }


class CodexJudgeProviderTests(unittest.TestCase):
    def _run_provider(self, output: str, *, model: str | None = None):
        captured: dict = {}

        def fake_run(command, **kwargs):
            if command[1:3] == ["login", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="Logged in using ChatGPT", stderr="")

            captured["command"] = command
            captured["prompt"] = kwargs["input"]
            captured["cwd"] = kwargs["cwd"]
            schema_path = Path(command[command.index("--output-schema") + 1])
            output_path = Path(command[command.index("--output-last-message") + 1])
            captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
            output_path.write_text(output, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        provider = CodexJudgeProvider(model=model, timeout_seconds=123)
        with (
            mock.patch.object(CodexJudgeProvider, "executable", return_value="codex.CMD"),
            mock.patch("app.analysis.providers.subprocess.run", side_effect=fake_run),
        ):
            result = provider.evaluate(
                system_prompt="평가 기준",
                user_prompt="평가 입력",
                result_model=TraceScorecard,
            )
        return result, captured

    def test_exec_uses_ephemeral_stdin_schema_and_read_only_temp_workspace(self) -> None:
        result, captured = self._run_provider(
            json.dumps(_scorecard_data(), ensure_ascii=False),
            model="judge-model",
        )

        command = captured["command"]
        self.assertEqual(result.overall.score, 8)
        self.assertIn("--ephemeral", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(command[command.index("--model") + 1], "judge-model")
        self.assertEqual(command[-1], "-")
        self.assertIn("평가 기준", captured["prompt"])
        self.assertIn("평가 입력", captured["prompt"])
        self.assertTrue(captured["cwd"].name.startswith("laimory-codex-llm-"))
        self.assertFalse(captured["schema"]["additionalProperties"])

    def test_general_text_output_does_not_request_schema(self) -> None:
        captured: dict = {}

        def fake_run(command, **kwargs):
            if command[1:3] == ["login", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="Logged in", stderr="")
            captured["command"] = command
            captured["prompt"] = kwargs["input"]
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text("개선책 본문", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        provider = CodexProvider(timeout_seconds=123)
        with (
            mock.patch.object(CodexProvider, "executable", return_value="codex.CMD"),
            mock.patch("app.analysis.providers.subprocess.run", side_effect=fake_run),
        ):
            result = provider.generate_text(system_prompt="작성 기준", user_prompt="문제점")

        self.assertEqual(result, "개선책 본문")
        self.assertNotIn("--output-schema", captured["command"])
        self.assertIn("작성 기준", captured["prompt"])
        self.assertIn("문제점", captured["prompt"])

    def test_empty_model_uses_cli_default(self) -> None:
        _, captured = self._run_provider(json.dumps(_scorecard_data()))
        self.assertNotIn("--model", captured["command"])

    def test_missing_executable_has_setup_error_code(self) -> None:
        with mock.patch.object(CodexJudgeProvider, "executable", return_value=None):
            with self.assertRaises(CodexNotInstalled) as caught:
                CodexJudgeProvider().evaluate(
                    system_prompt="기준",
                    user_prompt="입력",
                    result_model=TraceScorecard,
                )
        self.assertEqual(caught.exception.code, "CODEX_NOT_INSTALLED")

    def test_failed_login_status_is_not_authenticated(self) -> None:
        status = subprocess.CompletedProcess(["codex", "login", "status"], 1, "", "Not logged in")
        with (
            mock.patch.object(CodexJudgeProvider, "executable", return_value="codex.CMD"),
            mock.patch("app.analysis.providers.subprocess.run", return_value=status),
        ):
            with self.assertRaises(CodexNotAuthenticated) as caught:
                CodexJudgeProvider().evaluate(
                    system_prompt="기준",
                    user_prompt="입력",
                    result_model=TraceScorecard,
                )
        self.assertEqual(caught.exception.code, "CODEX_NOT_AUTHENTICATED")
        self.assertIn("codex login", str(caught.exception))

    def test_timeout_is_distinct(self) -> None:
        calls = 0

        def fake_run(command, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return subprocess.CompletedProcess(command, 0, "Logged in", "")
            raise subprocess.TimeoutExpired(command, timeout=1)

        with (
            mock.patch.object(CodexJudgeProvider, "executable", return_value="codex.CMD"),
            mock.patch("app.analysis.providers.subprocess.run", side_effect=fake_run),
        ):
            with self.assertRaises(CodexTimeout) as caught:
                CodexJudgeProvider(timeout_seconds=1).evaluate(
                    system_prompt="기준",
                    user_prompt="입력",
                    result_model=TraceScorecard,
                )
        self.assertEqual(caught.exception.code, "CODEX_TIMEOUT")

    def test_nonzero_exec_is_execution_failed(self) -> None:
        calls = 0

        def fake_run(command, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return subprocess.CompletedProcess(command, 0, "Logged in", "")
            return subprocess.CompletedProcess(command, 2, "", "model unavailable")

        with (
            mock.patch.object(CodexJudgeProvider, "executable", return_value="codex.CMD"),
            mock.patch("app.analysis.providers.subprocess.run", side_effect=fake_run),
        ):
            with self.assertRaises(CodexExecutionFailed) as caught:
                CodexJudgeProvider().evaluate(
                    system_prompt="기준",
                    user_prompt="입력",
                    result_model=TraceScorecard,
                )
        self.assertEqual(caught.exception.code, "CODEX_EXECUTION_FAILED")

    def test_invalid_json_and_schema_mismatch_are_distinct(self) -> None:
        with self.assertRaises(InvalidJudgeOutput) as invalid:
            self._run_provider("not-json")
        self.assertEqual(invalid.exception.code, "INVALID_JUDGE_OUTPUT")

        with self.assertRaises(JudgeSchemaValidationFailed) as mismatch:
            self._run_provider("{}")
        self.assertEqual(mismatch.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_generated_schema_forbids_extra_properties_recursively(self) -> None:
        schema = _strict_json_schema(TraceScorecard)
        objects: list[dict] = []

        def collect(node: object) -> None:
            if isinstance(node, dict):
                if node.get("type") == "object" or "properties" in node:
                    objects.append(node)
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(schema)
        self.assertTrue(objects)
        self.assertTrue(all(item.get("additionalProperties") is False for item in objects))


class JudgeProviderSelectionTests(unittest.TestCase):
    def test_codex_is_default_provider(self) -> None:
        settings = Settings(_env_file=None)
        with mock.patch("app.analysis.providers.get_settings", return_value=settings):
            self.assertIsInstance(get_llm_provider(), CodexProvider)
            self.assertIsInstance(get_judge_provider(), CodexJudgeProvider)

    def test_openai_api_provider_requires_explicit_selection(self) -> None:
        settings = Settings(_env_file=None, llm_provider="openai-api")
        with mock.patch("app.analysis.providers.get_settings", return_value=settings):
            self.assertIsInstance(get_llm_provider(), OpenAIApiProvider)
            self.assertIsInstance(get_judge_provider(), OpenAIApiJudgeProvider)

    def test_deprecated_openai_provider_keeps_structured_parse_behavior(self) -> None:
        expected = TraceScorecard.model_validate(_scorecard_data())
        parse = mock.Mock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=expected))]
            )
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
        )
        with (
            mock.patch("app.analysis.providers.get_openai_client", return_value=client),
            self.assertWarns(DeprecationWarning),
        ):
            result = OpenAIApiJudgeProvider(model="gpt-test").evaluate(
                system_prompt="기준",
                user_prompt="입력",
                result_model=TraceScorecard,
            )

        self.assertEqual(result, expected)
        self.assertEqual(parse.call_args.kwargs["response_format"], TraceScorecard)


if __name__ == "__main__":
    unittest.main()
