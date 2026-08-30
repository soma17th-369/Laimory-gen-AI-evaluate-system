"""설정 로딩.

LangFuse 접근 정보를 환경변수(`.env`)에서 읽는다. 키는 ``SecretStr`` 로 보관해
로그·화면·repr 에 값이 그대로 노출되지 않게 한다. 값 자체는 어디에도 남기지 않는다.

LangFuse 프로젝트는 환경마다 따로 있다(→ [app.environments][]). 그래서 키도 환경별로 읽는다.

| 환경 | public/secret | host |
| --- | --- | --- |
| `dev` | `LANGFUSE_DEV_PUBLIC_KEY` / `LANGFUSE_DEV_SECRET_KEY` (없으면 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`) | `LANGFUSE_DEV_HOST` → `LANGFUSE_HOST` |
| `prod` | `LANGFUSE_PROD_PUBLIC_KEY` / `LANGFUSE_PROD_SECRET_KEY` | `LANGFUSE_PROD_HOST` → `LANGFUSE_HOST` |

접두사 없는 이름(`LANGFUSE_PUBLIC_KEY` …)은 환경 구분이 없던 시절의 이름이라 **dev 기본값**
으로만 쓴다. 이미 쓰던 `.env` 를 그대로 두고 prod 키 두 줄만 더해도 동작한다. host 는 두
프로젝트가 같은 인스턴스에 있는 경우가 흔해서 공통 `LANGFUSE_HOST` 로 떨어진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import environments


@dataclass(frozen=True)
class LangfuseCredentials:
    """환경 하나의 LangFuse 접근 정보. 값은 ``SecretStr`` 로만 들고 다닌다."""

    environment: str
    public_key: SecretStr | None
    secret_key: SecretStr | None
    host: str

    @property
    def is_complete(self) -> bool:
        """public/secret 키가 모두 있는지(= 이 환경으로 조회할 수 있는지)."""
        return self.public_key is not None and self.secret_key is not None


class Settings(BaseSettings):
    """환경변수 기반 설정.

    LangFuse 키는 환경별 접두사(``LANGFUSE_DEV_*`` / ``LANGFUSE_PROD_*``)로 읽는다. 어떤
    이름이 어떤 환경으로 가는지는 [langfuse_credentials][app.config.Settings.langfuse_credentials]
    한 곳에서만 정한다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 환경 구분이 없던 시절의 이름. dev 기본값·공통 host 로만 쓴다.
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    langfuse_dev_public_key: SecretStr | None = None
    langfuse_dev_secret_key: SecretStr | None = None
    langfuse_dev_host: str | None = None

    langfuse_prod_public_key: SecretStr | None = None
    langfuse_prod_secret_key: SecretStr | None = None
    langfuse_prod_host: str | None = None

    # 모든 LLM 기능의 공통 provider. 기본은 로컬에 로그인된 Codex CLI이고 OpenAI API는 호환용.
    llm_provider: Literal["codex", "openai-api"] = "codex"
    codex_model: str | None = None
    codex_timeout_seconds: int = 600

    # Deprecated OpenAI API provider 호환용.
    openai_api_key: SecretStr | None = None
    openai_judge_model: str = "gpt-4o"

    # 파일 저장 루트(로그·평가·개선책·테스트데이터). 프로젝트 루트 기준 상대경로. gitignore 대상.
    data_dir: str = "data"

    def langfuse_credentials(self, env: str) -> LangfuseCredentials:
        """환경 하나의 접근 정보.

        환경을 늘리면 아래 표에 줄을 추가한다. 표에 없는 환경은 `KeyError` 로 바로 드러난다.
        """
        resolved = environments.validate(env)
        by_environment = {
            environments.DEV: (
                self.langfuse_dev_public_key or self.langfuse_public_key,
                self.langfuse_dev_secret_key or self.langfuse_secret_key,
                self.langfuse_dev_host,
            ),
            environments.PROD: (
                self.langfuse_prod_public_key,
                self.langfuse_prod_secret_key,
                self.langfuse_prod_host,
            ),
        }
        public_key, secret_key, host = by_environment[resolved]
        return LangfuseCredentials(
            environment=resolved,
            public_key=public_key,
            secret_key=secret_key,
            host=host or self.langfuse_host,
        )

    def has_langfuse_credentials(self, env: str) -> bool:
        """그 환경의 public/secret 키가 모두 설정됐는지."""
        return self.langfuse_credentials(env).is_complete

    def configured_environments(self) -> list[str]:
        """키가 갖춰져 실제로 조회할 수 있는 환경 목록(선언 순서)."""
        return [env for env in environments.ENVIRONMENTS if self.has_langfuse_credentials(env)]

    def has_openai_credentials(self) -> bool:
        """Deprecated OpenAI API provider용 키가 설정됐는지."""
        return self.openai_api_key is not None


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. 프로세스 동안 한 번만 읽는다."""
    return Settings()
