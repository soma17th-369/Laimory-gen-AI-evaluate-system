from __future__ import annotations

import unittest
from unittest import mock

from langfuse.api.core.api_error import ApiError

from app import langfuse_client


class RateLimitWaitTests(unittest.TestCase):
    """호출 한도(429)는 기다렸다가 다시 부르고, 다른 오류는 그대로 올린다."""

    def test_waits_for_retry_after_then_calls_again(self) -> None:
        answers = [ApiError(status_code=429, headers={"Retry-After": "7"}), "ok"]

        def call():
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(langfuse_client.time, "sleep") as sleep:
            self.assertEqual(langfuse_client._wait_on_rate_limit(call), "ok")

        sleep.assert_called_once_with(8.0)

    def test_other_errors_are_not_retried(self) -> None:
        call = mock.Mock(side_effect=ApiError(status_code=500))

        with mock.patch.object(langfuse_client.time, "sleep") as sleep:
            with self.assertRaises(ApiError):
                langfuse_client._wait_on_rate_limit(call)

        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    def test_gives_up_when_the_limit_never_clears(self) -> None:
        call = mock.Mock(side_effect=ApiError(status_code=429, headers={}))

        with mock.patch.object(langfuse_client.time, "sleep") as sleep:
            with self.assertRaises(ApiError):
                langfuse_client._wait_on_rate_limit(call)

        self.assertEqual(call.call_count, langfuse_client.RATE_LIMIT_MAX_WAITS + 1)
        sleep.assert_called_with(langfuse_client.RATE_LIMIT_DEFAULT_WAIT_SECONDS + 1)


if __name__ == "__main__":
    unittest.main()
