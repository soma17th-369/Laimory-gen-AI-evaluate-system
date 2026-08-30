"""LLM-as-a-Judge 실행 provider.

기본 provider는 ChatGPT 계정으로 인증된 로컬 Codex CLI다. OpenAI API 직접 호출 구현은 기존
동작 호환을 위해 남기되 deprecated provider로만 명시적으로 선택할 수 있다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_settings

JudgeResult = TypeVar("JudgeResult", bound=BaseModel)


class LlmProvider(Protocol):
    """상위 LLM 기능이 의존하는 공통 provider 계약."""

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        """일반 텍스트 최종 결과를 반환한다."""

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        result_model: type[JudgeResult],
    ) -> JudgeResult:
        """JSON Schema에 맞게 검증된 도메인 모델을 반환한다."""

    def evaluate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        result_model: type[JudgeResult],
    ) -> JudgeResult:
        """두 프롬프트를 평가하고 검증된 도메인 모델을 반환한다."""


# 기존 이름을 import하던 코드와 설명의 호환성을 유지한다.
JudgeProvider = LlmProvider


class JudgeProviderError(RuntimeError):
    """사용자에게 해결 방법을 안내할 수 있는 provider 오류."""

    code = "JUDGE_PROVIDER_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CodexNotInstalled(JudgeProviderError):
    code = "CODEX_NOT_INSTALLED"


class CodexNotAuthenticated(JudgeProviderError):
    code = "CODEX_NOT_AUTHENTICATED"


class CodexExecutionFailed(JudgeProviderError):
    code = "CODEX_EXECUTION_FAILED"


class CodexTimeout(JudgeProviderError):
    code = "CODEX_TIMEOUT"


class InvalidJudgeOutput(JudgeProviderError):
    code = "INVALID_JUDGE_OUTPUT"


class JudgeSchemaValidationFailed(JudgeProviderError):
    code = "SCHEMA_VALIDATION_FAILED"


class OpenAINotConfigured(JudgeProviderError):
    code = "OPENAI_NOT_CONFIGURED"


@lru_cache
def get_openai_client() -> OpenAI:
    """Deprecated OpenAI API provider가 사용하는 client."""
    settings = get_settings()
    if not settings.has_openai_credentials():
        raise OpenAINotConfigured(
            "OPENAI_API_KEY가 없습니다. .env에 설정하세요(.env.example 참고)."
        )
    return OpenAI(api_key=settings.openai_api_key.get_secret_value())


def _strict_json_schema(result_model: type[BaseModel]) -> dict:
    """Pydantic schema의 모든 object에서 미정의 필드를 금지한다."""
    schema = result_model.model_json_schema()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def _subprocess_options() -> dict:
    """Windows GUI 앱에서 별도 콘솔 창이 뜨지 않게 하는 공통 옵션."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _short_error(text: str, *, limit: int = 1200) -> str:
    """CLI stderr를 사용자에게 필요한 길이만 남긴다."""
    compact = " ".join(text.strip().split())
    if not compact:
        return "Codex CLI가 상세 오류를 반환하지 않았습니다."
    return compact if len(compact) <= limit else f"{compact[:limit]}…"


def _looks_like_auth_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "not logged in",
            "not authenticated",
            "authentication required",
            "unauthorized",
            "401",
            "codex login",
        )
    )


class CodexProvider:
    """`codex exec`와 저장된 Codex CLI 인증을 사용하는 기본 LLM provider."""

    def __init__(self, *, model: str | None = None, timeout_seconds: int = 600) -> None:
        self.model = model.strip() if model and model.strip() else None
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def executable() -> str | None:
        """PATH에서 실제 실행할 Codex CLI 경로를 찾는다."""
        return shutil.which("codex")

    def _require_authenticated_cli(self) -> str:
        executable = self.executable()
        if executable is None:
            raise CodexNotInstalled(
                "Codex CLI를 찾을 수 없습니다. 설치 후 PowerShell에서 `codex --version`을 확인하세요."
            )

        try:
            status = subprocess.run(
                [executable, "login", "status"],
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
                **_subprocess_options(),
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexTimeout(
                "Codex CLI 인증 상태 확인이 시간 안에 끝나지 않았습니다. PowerShell에서 "
                "`codex login status`를 확인하세요."
            ) from exc
        except OSError as exc:
            raise CodexExecutionFailed(f"Codex CLI를 실행하지 못했습니다: {exc}") from exc

        if status.returncode != 0:
            raise CodexNotAuthenticated(
                "Codex CLI가 인증되어 있지 않습니다. PowerShell에서 `codex login`을 실행하고 "
                "ChatGPT 계정으로 로그인하세요."
            )
        return executable

    def _run(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        result_model: type[BaseModel] | None,
    ) -> str:
        executable = self._require_authenticated_cli()
        output_instruction = (
            "제공된 JSON Schema에 맞는 최종 결과만 반환하라."
            if result_model is not None
            else "요청된 최종 내용만 반환하고 작업 과정이나 메타 설명은 덧붙이지 마라."
        )
        prompt = (
            "아래 지시와 입력만 사용해 독립적으로 작업한다. 파일을 탐색하거나 도구를 호출하지 말고, "
            f"{output_instruction}\n\n"
            f"<system_instruction>\n{system_prompt}\n</system_instruction>\n\n"
            f"<user_input>\n{user_prompt}\n</user_input>"
        )

        try:
            with tempfile.TemporaryDirectory(prefix="laimory-codex-llm-") as directory:
                root = Path(directory)
                schema_path = root / "output_schema.json"
                output_path = root / "output.txt"

                command = [
                    executable,
                    "exec",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--color",
                    "never",
                    "--output-last-message",
                    str(output_path),
                ]
                if result_model is not None:
                    schema_path.write_text(
                        json.dumps(
                            _strict_json_schema(result_model),
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    command.extend(["--output-schema", str(schema_path)])
                if self.model:
                    command.extend(["--model", self.model])
                command.append("-")

                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=root,
                    timeout=self.timeout_seconds,
                    check=False,
                    **_subprocess_options(),
                )
                if completed.returncode != 0:
                    detail = _short_error(completed.stderr or completed.stdout)
                    if _looks_like_auth_error(detail):
                        raise CodexNotAuthenticated(
                            "Codex CLI 인증이 만료되었거나 유효하지 않습니다. PowerShell에서 "
                            "`codex login`을 실행한 뒤 다시 시도하세요."
                        )
                    raise CodexExecutionFailed(f"Codex CLI LLM 실행이 실패했습니다: {detail}")

                raw_output = (
                    output_path.read_text(encoding="utf-8")
                    if output_path.exists()
                    else completed.stdout
                )
        except subprocess.TimeoutExpired as exc:
            raise CodexTimeout(
                f"Codex CLI LLM 실행이 {self.timeout_seconds}초 안에 끝나지 않았습니다. "
                "CODEX_TIMEOUT_SECONDS를 늘리거나 입력 크기를 확인하세요."
            ) from exc
        except JudgeProviderError:
            raise
        except OSError as exc:
            raise CodexExecutionFailed(
                f"Codex CLI 출력 파일 또는 프로세스 처리에 실패했습니다: {exc}"
            ) from exc

        return raw_output

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        """Codex의 최종 메시지를 일반 텍스트로 반환한다."""
        output = self._run(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            result_model=None,
        ).strip()
        if not output:
            raise InvalidJudgeOutput("Codex CLI가 빈 최종 결과를 반환했습니다.")
        return output

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        result_model: type[JudgeResult],
    ) -> JudgeResult:
        """Codex structured output을 JSON으로 읽고 Pydantic으로 재검증한다."""
        raw_output = self._run(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            result_model=result_model,
        )

        try:
            payload = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError) as exc:
            raise InvalidJudgeOutput(
                f"Codex CLI가 유효한 JSON 결과를 반환하지 않았습니다: {_short_error(raw_output)}"
            ) from exc

        try:
            return result_model.model_validate(payload)
        except ValidationError as exc:
            raise JudgeSchemaValidationFailed(
                f"Codex CLI 결과가 Evaluation Schema와 맞지 않습니다: {exc}"
            ) from exc

    def evaluate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        result_model: type[JudgeResult],
    ) -> JudgeResult:
        """Judge 호출 호환용 별칭."""
        return self.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            result_model=result_model,
        )


# 최초 Judge 전환에서 공개한 이름을 유지한다.
CodexJudgeProvider = CodexProvider


class OpenAIApiProvider:
    """Deprecated: OpenAI API를 직접 호출하는 기존 LLM provider."""

    def __init__(self, *, model: str) -> None:
        self.model = model

    @staticmethod
    def _warn_deprecated() -> None:
        warnings.warn(
            "OpenAIApiProvider는 deprecated입니다. 기본 CodexProvider를 사용하세요.",
            DeprecationWarning,
            stacklevel=3,
        )

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        self._warn_deprecated()
        client = get_openai_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        def create(**extra):
            return client.chat.completions.create(
                model=self.model,
                messages=messages,
                **extra,
            )

        try:
            completion = create(temperature=0)
        except Exception as exc:  # noqa: BLE001
            if "temperature" in str(exc).lower():
                completion = create()
            else:
                raise
        output = completion.choices[0].message.content or ""
        if not output.strip():
            raise InvalidJudgeOutput("OpenAI API가 빈 최종 결과를 반환했습니다.")
        return output

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        result_model: type[JudgeResult],
    ) -> JudgeResult:
        self._warn_deprecated()
        client = get_openai_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        def parse(**extra):
            return client.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=result_model,
                **extra,
            )

        try:
            completion = parse(temperature=0)
        except Exception as exc:  # noqa: BLE001
            if "temperature" in str(exc).lower():
                completion = parse()
            else:
                raise

        result = completion.choices[0].message.parsed
        if result is None:
            raise InvalidJudgeOutput(
                "OpenAI API가 구조화 결과를 반환하지 않았습니다(거부 또는 형식 실패)."
            )
        return result

    def evaluate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        result_model: type[JudgeResult],
    ) -> JudgeResult:
        """Judge 호출 호환용 별칭."""
        return self.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            result_model=result_model,
        )


OpenAIApiJudgeProvider = OpenAIApiProvider


def get_llm_provider() -> LlmProvider:
    """모든 LLM 기능에 설정된 provider를 만든다. 자동 fallback은 하지 않는다."""
    settings = get_settings()
    if settings.llm_provider == "codex":
        return CodexProvider(
            model=settings.codex_model,
            timeout_seconds=settings.codex_timeout_seconds,
        )
    return OpenAIApiProvider(model=settings.openai_judge_model)


def get_judge_provider() -> JudgeProvider:
    """기존 Judge 진입점. 실제 선택은 공통 LLM provider 설정을 따른다."""
    return get_llm_provider()


def llm_provider_label() -> str:
    """모든 LLM UI에서 쓸 현재 provider 표시명."""
    settings = get_settings()
    if settings.llm_provider == "codex":
        model = settings.codex_model.strip() if settings.codex_model else ""
        return f"Codex CLI · {model}" if model else "Codex CLI · CLI 기본 모델"
    return f"OpenAI API (deprecated) · {settings.openai_judge_model}"


def llm_setup_error() -> str | None:
    """LLM 버튼을 누르기 전에 알 수 있는 필수 설정 누락만 반환한다."""
    settings = get_settings()
    if settings.llm_provider == "codex" and CodexProvider.executable() is None:
        return "Codex CLI를 찾을 수 없습니다. 설치 후 `codex login`으로 ChatGPT 계정에 로그인하세요."
    if settings.llm_provider == "openai-api" and not settings.has_openai_credentials():
        return "OpenAI API provider를 사용하려면 .env에 OPENAI_API_KEY가 필요합니다."
    return None


judge_provider_label = llm_provider_label
judge_setup_error = llm_setup_error
