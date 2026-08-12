"""설정 로딩.

LangFuse 접근 정보를 환경변수(`.env`)에서 읽는다. 키는 ``SecretStr`` 로 보관해
로그·화면·repr 에 값이 그대로 노출되지 않게 한다. 값 자체는 어디에도 남기지 않는다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 기반 설정.

    LangFuse SDK 와 같은 이름(``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` /
    ``LANGFUSE_HOST``)을 그대로 읽는다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # OpenAI (M2 채점/분석용). 키가 없으면 채점 기능만 비활성되고 조회는 정상.
    openai_api_key: SecretStr | None = None
    openai_judge_model: str = "gpt-4o"

    # 파일 저장 루트(로그·평가·개선책·테스트데이터). 프로젝트 루트 기준 상대경로. gitignore 대상.
    data_dir: str = "data"

    def has_langfuse_credentials(self) -> bool:
        """public/secret 키가 모두 설정됐는지."""
        return self.langfuse_public_key is not None and self.langfuse_secret_key is not None

    def has_openai_credentials(self) -> bool:
        """OpenAI 키가 설정됐는지(채점 가능 여부)."""
        return self.openai_api_key is not None


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. 프로세스 동안 한 번만 읽는다."""
    return Settings()
