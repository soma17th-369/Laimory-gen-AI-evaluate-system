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


class GetTraceTests(unittest.TestCase):
    def _client(self, *answers) -> mock.Mock:
        client = mock.Mock()
        client.api.trace.get.side_effect = list(answers)
        return client

    def test_waits_for_the_rate_limit_like_the_list_call(self) -> None:
        client = self._client(ApiError(status_code=429, headers={"Retry-After": "2"}), "상세")

        with (
            mock.patch.object(langfuse_client, "get_client", return_value=client),
            mock.patch.object(langfuse_client.time, "sleep") as sleep,
        ):
            self.assertEqual(langfuse_client.get_trace("t1", "dev"), "상세")

        sleep.assert_called_once_with(3.0)

    def test_missing_trace_has_its_own_error(self) -> None:
        client = self._client(ApiError(status_code=404))

        with mock.patch.object(langfuse_client, "get_client", return_value=client):
            with self.assertRaises(langfuse_client.TraceNotFound):
                langfuse_client.get_trace("t1", "dev")

    def test_other_errors_stay_as_they_are(self) -> None:
        client = self._client(ApiError(status_code=500))

        with mock.patch.object(langfuse_client, "get_client", return_value=client):
            with self.assertRaises(ApiError):
                langfuse_client.get_trace("t1", "dev")


if __name__ == "__main__":
    unittest.main()
