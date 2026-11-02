"""작업 표 — 뒤에서 돌리고, 같은 일은 겹치지 않게 한다."""

from __future__ import annotations

import threading
import unittest

from app.tasks import jobs


def _describe(exc: Exception) -> dict[str, str]:
    return {"code": "FAILED", "message": str(exc)}


class JobBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.board = jobs.JobBoard({"judge": 1}, _describe)
        self.release = threading.Event()
        self.addCleanup(self.release.set)
        self.addCleanup(self.board.shutdown)

    def _wait(self, job: jobs.Job) -> jobs.Job:
        finished = threading.Event()
        self.board._pools[job.kind].submit(finished.set)
        finished.wait(timeout=10)
        return job

    def _blocked(self, _job: jobs.Job) -> str:
        self.release.wait(timeout=10)
        return "끝"

    def test_result_is_kept_after_the_work_ends(self) -> None:
        job = self._wait(self.board.submit("judge", "a", lambda _job: {"점수": 1}))

        self.assertEqual((job.status, job.result, job.error), (jobs.DONE, {"점수": 1}, None))
        self.assertIs(self.board.get(job.job_id), job)

    def test_failure_is_described_instead_of_raised(self) -> None:
        def fail(_job: jobs.Job) -> None:
            raise ValueError("막힘")

        job = self._wait(self.board.submit("judge", "a", fail))

        self.assertEqual(job.status, jobs.FAILED)
        self.assertEqual(job.error, {"code": "FAILED", "message": "막힘"})

    def test_same_key_returns_the_running_job(self) -> None:
        first = self.board.submit("judge", "a", self._blocked)

        second = self.board.submit("judge", "a", lambda _job: self.fail("다시 돌면 안 된다"))

        self.assertIs(first, second)

    def test_same_key_runs_again_after_it_finished(self) -> None:
        first = self._wait(self.board.submit("judge", "a", lambda _job: 1))

        second = self._wait(self.board.submit("judge", "a", lambda _job: 2))

        self.assertIsNot(first, second)
        self.assertEqual(second.result, 2)

    def test_work_beyond_the_limit_waits_its_turn(self) -> None:
        self.board.submit("judge", "a", self._blocked)

        waiting = self.board.submit("judge", "b", lambda _job: "둘째")

        self.assertEqual(waiting.status, jobs.QUEUED)
        self.release.set()
        self._wait(waiting)
        self.assertEqual(waiting.status, jobs.DONE)

    def test_work_can_report_progress(self) -> None:
        def work(job: jobs.Job) -> None:
            job.total = 2
            job.done += 1

        job = self._wait(self.board.submit("judge", "a", work))

        self.assertEqual((job.done, job.total), (1, 2))

    def test_shutdown_drops_waiting_work(self) -> None:
        ran: list[str] = []
        self.board.submit("judge", "a", self._blocked)
        waiting = self.board.submit("judge", "b", lambda _job: ran.append("둘째"))

        self.board.shutdown()
        self.release.set()
        self.board._pools["judge"].shutdown(wait=True)

        self.assertEqual(ran, [])
        self.assertEqual(waiting.status, jobs.QUEUED)

    def test_shutdown_tells_running_work_to_stop(self) -> None:
        self.assertFalse(self.board.stopping.is_set())

        self.board.shutdown()

        self.assertTrue(self.board.stopping.is_set())

    def test_unknown_id_is_none(self) -> None:
        self.assertIsNone(self.board.get("없음"))


if __name__ == "__main__":
    unittest.main()
