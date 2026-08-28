"""환경(dev·prod) 계약 — 행이 어느 프로젝트에서 왔는지, 키를 어떤 이름으로 읽는지."""

from __future__ import annotations

import unittest
from unittest import mock

from app import environments
from app.config import Settings
from app.langfuse_client import LangfuseNotConfigured, get_client


def _settings(**overrides) -> Settings:
    """실제 `.env` 를 읽지 않는 설정(테스트가 준 값만 본다)."""
    return Settings(_env_file=None, **overrides)


class EnvironmentOfRecordTests(unittest.TestCase):
    def test_row_reports_the_project_it_came_from(self) -> None:
        self.assertEqual(environments.of({"id": "t1", "env": "prod"}), environments.PROD)
        self.assertEqual(environments.of({"id": "t1", "env": "dev"}), environments.DEV)

    def test_record_without_env_is_dev(self) -> None:
        """환경 구분이 생기기 전 데이터는 개발 프로젝트 하나만 보던 시절 것이다."""
        self.assertEqual(environments.of({"id": "t1"}), environments.DEV)
        self.assertEqual(environments.of(None), environments.DEV)

    def test_unknown_env_value_is_not_trusted(self) -> None:
        self.assertEqual(environments.of({"env": "staging"}), environments.DEV)

    def test_validate_rejects_unknown_environments(self) -> None:
        self.assertEqual(environments.validate(environments.PROD), environments.PROD)
        with self.assertRaises(environments.UnknownEnvironment):
            environments.validate("staging")

    def test_labels_exist_for_every_environment(self) -> None:
        for env in environments.ENVIRONMENTS:
            with self.subTest(env):
                self.assertNotEqual(environments.label(env), env)
                self.assertTrue(environments.short_label(env))


class CredentialResolutionTests(unittest.TestCase):
    def test_each_environment_reads_its_own_prefixed_keys(self) -> None:
        settings = _settings(
            langfuse_dev_public_key="pk-dev",
            langfuse_dev_secret_key="sk-dev",
            langfuse_prod_public_key="pk-prod",
            langfuse_prod_secret_key="sk-prod",
        )

        dev = settings.langfuse_credentials(environments.DEV)
        prod = settings.langfuse_credentials(environments.PROD)

        self.assertEqual(dev.public_key.get_secret_value(), "pk-dev")
        self.assertEqual(prod.public_key.get_secret_value(), "pk-prod")
        self.assertEqual(settings.configured_environments(), [environments.DEV, environments.PROD])

    def test_unprefixed_legacy_keys_are_read_as_dev_only(self) -> None:
        settings = _settings(langfuse_public_key="pk-old", langfuse_secret_key="sk-old")

        self.assertTrue(settings.has_langfuse_credentials(environments.DEV))
        self.assertFalse(settings.has_langfuse_credentials(environments.PROD))
        self.assertEqual(settings.configured_environments(), [environments.DEV])

    def test_prefixed_dev_keys_win_over_the_legacy_names(self) -> None:
        settings = _settings(
            langfuse_public_key="pk-old",
            langfuse_secret_key="sk-old",
            langfuse_dev_public_key="pk-dev",
            langfuse_dev_secret_key="sk-dev",
        )

        self.assertEqual(
            settings.langfuse_credentials(environments.DEV).public_key.get_secret_value(), "pk-dev"
        )

    def test_host_falls_back_to_the_shared_one_and_is_overridable_per_environment(self) -> None:
        settings = _settings(
            langfuse_host="https://jp.cloud.langfuse.com",
            langfuse_prod_host="https://self-hosted.internal",
        )

        self.assertEqual(
            settings.langfuse_credentials(environments.DEV).host, "https://jp.cloud.langfuse.com"
        )
        self.assertEqual(
            settings.langfuse_credentials(environments.PROD).host, "https://self-hosted.internal"
        )

    def test_client_refuses_to_start_when_that_environment_has_no_keys(self) -> None:
        with mock.patch("app.langfuse_client.get_settings", return_value=_settings()):
            with self.assertRaises(LangfuseNotConfigured) as caught:
                get_client(environments.PROD)

        self.assertIn("LANGFUSE_PROD_PUBLIC_KEY", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
