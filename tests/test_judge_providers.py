from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.analysis.providers import (
    ClaudeCodeProvider,
    ClaudeExecutionFailed,
    ClaudeNotAuthenticated,
    ClaudeNotInstalled,
    ClaudeTimeout,
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
    llm_provider_label,
    llm_setup_error,
)
from app.analysis import stage_schema, stages
from app.config import Settings

# 구조화 출력 계약은 단계별 채점 모델이다(배점표에서 만들어진다).
StageScorecard = stage_schema.scorecard_model("question")


def _scorecard_data() -> dict:
    return {
        "items": {
            item.key: {"score": item.points, "applied": True, "reason": "점수 근거"}
            for item in stages.get("question").items
        },
        "deductions": [],
        "alerts": [],
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
                result_model=StageScorecard,
            )
        return result, captured

    def test_exec_uses_ephemeral_stdin_schema_and_read_only_temp_workspace(self) -> None:
        result, captured = self._run_provider(
            json.dumps(_scorecard_data(), ensure_ascii=False),
            model="judge-model",
        )

        command = captured["command"]
        self.assertEqual(result.items.reflection.score, 30)
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
                    result_model=StageScorecard,
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
                    result_model=StageScorecard,
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
                    result_model=StageScorecard,
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
                    result_model=StageScorecard,
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
        schema = _strict_json_schema(StageScorecard)
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

    def test_ref_keeps_no_sibling_keywords(self) -> None:
        """strict 모드는 `$ref` 옆의 description 을 거부한다(중첩 모델 필드에서 생긴다)."""
        schema = _strict_json_schema(StageScorecard)
        refs: list[dict] = []

        def collect(node: object) -> None:
            if isinstance(node, dict):
                if "$ref" in node:
                    refs.append(node)
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(schema)
        self.assertTrue(refs)
        self.assertTrue(all(set(item) == {"$ref"} for item in refs))


_LOGGED_IN = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})


def _envelope(**fields) -> str:
    """`claude -p --output-format json` 결과 envelope(실물에서 쓰는 필드만)."""
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, **fields}, ensure_ascii=False)


class ClaudeCodeProviderTests(unittest.TestCase):
    def _run(self, stdout: str, *, returncode: int = 0, model: str | None = None, result_model=StageScorecard):
        captured: dict = {}

        def fake_run(command, **kwargs):
            if command[1:3] == ["auth", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout=_LOGGED_IN, stderr="")
            captured["command"] = command
            captured["prompt"] = kwargs["input"]
            captured["cwd"] = kwargs["cwd"]
            # 시스템 프롬프트 파일은 호출이 끝나면 임시 디렉터리와 함께 사라지므로 여기서 읽는다.
            system_path = Path(command[command.index("--system-prompt-file") + 1])
            captured["system_prompt"] = system_path.read_text(encoding="utf-8")
            if "--json-schema" in command:
                captured["schema"] = json.loads(command[command.index("--json-schema") + 1])
            return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

        provider = ClaudeCodeProvider(model=model, timeout_seconds=123)
        with (
            mock.patch.object(ClaudeCodeProvider, "executable", return_value="claude.EXE"),
            mock.patch("app.analysis.providers.subprocess.run", side_effect=fake_run),
        ):
            if result_model is None:
                result = provider.generate_text(system_prompt="평가 기준", user_prompt="평가 입력")
            else:
                result = provider.evaluate(
                    system_prompt="평가 기준",
                    user_prompt="평가 입력",
                    result_model=result_model,
                )
        return result, captured

    def test_print_mode_is_isolated_and_reads_structured_output(self) -> None:
        data = _scorecard_data()
        result, captured = self._run(
            _envelope(result=json.dumps(data, ensure_ascii=False), structured_output=data),
            model="sonnet",
        )

        command = captured["command"]
        self.assertEqual(result.items.reflection.score, 30)
        self.assertIn("-p", command)
        self.assertEqual(command[command.index("--output-format") + 1], "json")
        self.assertIn("--no-session-persistence", command)
        self.assertIn("--safe-mode", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--model") + 1], "sonnet")
        self.assertEqual(captured["system_prompt"], "평가 기준")
        self.assertEqual(captured["prompt"], "평가 입력")
        self.assertTrue(captured["cwd"].name.startswith("laimory-claude-llm-"))
        self.assertFalse(captured["schema"]["additionalProperties"])

    def test_general_text_output_does_not_request_schema(self) -> None:
        result, captured = self._run(_envelope(result="  개선책 본문\n"), result_model=None)

        self.assertEqual(result, "개선책 본문")
        self.assertNotIn("--json-schema", captured["command"])

    def test_empty_model_uses_cli_default(self) -> None:
        data = _scorecard_data()
        _, captured = self._run(_envelope(structured_output=data), model="  ")
        self.assertNotIn("--model", captured["command"])

    def test_missing_executable_has_setup_error_code(self) -> None:
        with mock.patch.object(ClaudeCodeProvider, "executable", return_value=None):
            with self.assertRaises(ClaudeNotInstalled) as caught:
                ClaudeCodeProvider().generate_text(system_prompt="기준", user_prompt="입력")
        self.assertEqual(caught.exception.code, "CLAUDE_NOT_INSTALLED")

    def test_logged_out_status_is_not_authenticated(self) -> None:
        for returncode, stdout in ((1, json.dumps({"loggedIn": False})), (0, json.dumps({"loggedIn": False}))):
            status = subprocess.CompletedProcess(["claude", "auth", "status"], returncode, stdout, "")
            with (
                mock.patch.object(ClaudeCodeProvider, "executable", return_value="claude.EXE"),
                mock.patch("app.analysis.providers.subprocess.run", return_value=status),
            ):
                with self.assertRaises(ClaudeNotAuthenticated) as caught:
                    ClaudeCodeProvider().generate_text(system_prompt="기준", user_prompt="입력")
            self.assertEqual(caught.exception.code, "CLAUDE_NOT_AUTHENTICATED")
            self.assertIn("claude auth login", str(caught.exception))

    def test_timeout_is_distinct(self) -> None:
        def fake_run(command, **kwargs):
            if command[1:3] == ["auth", "status"]:
                return subprocess.CompletedProcess(command, 0, _LOGGED_IN, "")
            raise subprocess.TimeoutExpired(command, timeout=1)

        with (
            mock.patch.object(ClaudeCodeProvider, "executable", return_value="claude.EXE"),
            mock.patch("app.analysis.providers.subprocess.run", side_effect=fake_run),
        ):
            with self.assertRaises(ClaudeTimeout) as caught:
                ClaudeCodeProvider(timeout_seconds=1).generate_text(system_prompt="기준", user_prompt="입력")
        self.assertEqual(caught.exception.code, "CLAUDE_TIMEOUT")
        self.assertIn("CLAUDE_TIMEOUT_SECONDS", str(caught.exception))

    def test_error_envelope_is_execution_failed_with_cli_message(self) -> None:
        # 실물: 실패해도 stdout에 is_error envelope가 오고 stderr는 비어 있다.
        stdout = _envelope(is_error=True, result="Failed to refresh OAuth token: retry in a minute")
        with self.assertRaises(ClaudeExecutionFailed) as caught:
            self._run(stdout, returncode=1)
        self.assertEqual(caught.exception.code, "CLAUDE_EXECUTION_FAILED")
        self.assertIn("Failed to refresh OAuth token", str(caught.exception))

    def test_auth_error_envelope_is_not_authenticated(self) -> None:
        stdout = _envelope(is_error=True, result="Invalid API key · Please run /login")
        with self.assertRaises(ClaudeNotAuthenticated):
            self._run(stdout, returncode=1)

    def test_invalid_json_and_schema_mismatch_are_distinct(self) -> None:
        with self.assertRaises(InvalidJudgeOutput) as invalid:
            self._run(_envelope(result="not-json"))
        self.assertEqual(invalid.exception.code, "INVALID_JUDGE_OUTPUT")

        with self.assertRaises(JudgeSchemaValidationFailed) as mismatch:
            self._run(_envelope(result="{}", structured_output={}))
        self.assertEqual(mismatch.exception.code, "SCHEMA_VALIDATION_FAILED")


class JudgeProviderSelectionTests(unittest.TestCase):
    def test_codex_is_default_provider(self) -> None:
        settings = Settings(_env_file=None)
        with mock.patch("app.analysis.providers.get_settings", return_value=settings):
            self.assertIsInstance(get_llm_provider(), CodexProvider)
            self.assertIsInstance(get_judge_provider(), CodexJudgeProvider)

    def test_claude_provider_is_selected_with_its_own_settings(self) -> None:
        settings = Settings(
            _env_file=None, llm_provider="claude", claude_model="opus", claude_timeout_seconds=42
        )
        with mock.patch("app.analysis.providers.get_settings", return_value=settings):
            provider = get_llm_provider()
            self.assertIsInstance(provider, ClaudeCodeProvider)
            self.assertIsInstance(get_judge_provider(), ClaudeCodeProvider)
            self.assertEqual((provider.model, provider.timeout_seconds), ("opus", 42))
            self.assertEqual(llm_provider_label(), "Claude Code CLI · opus")
            with mock.patch.object(ClaudeCodeProvider, "executable", return_value=None):
                self.assertIn("claude auth login", llm_setup_error())

    def test_openai_api_provider_requires_explicit_selection(self) -> None:
        settings = Settings(_env_file=None, llm_provider="openai-api")
        with mock.patch("app.analysis.providers.get_settings", return_value=settings):
            self.assertIsInstance(get_llm_provider(), OpenAIApiProvider)
            self.assertIsInstance(get_judge_provider(), OpenAIApiJudgeProvider)

    def test_deprecated_openai_provider_keeps_structured_parse_behavior(self) -> None:
        expected = StageScorecard.model_validate(_scorecard_data())
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
                result_model=StageScorecard,
            )

        self.assertEqual(result, expected)
        self.assertEqual(parse.call_args.kwargs["response_format"], StageScorecard)


if __name__ == "__main__":
    unittest.main()
