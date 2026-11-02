"""오래 걸리는 작업의 표 — 수집·채점을 뒤에서 돌리고 상태를 알려준다.

표는 **프로세스 메모리에만** 있다. 프로세스가 끝나면 작업 id 는 사라지지만, 끝난 단계의 채점 결과와 받은
로그는 저장소에 남으므로 잃는 것은 진행 표시뿐이다.

종류별로 동시에 도는 수를 제한한다. 채점 한 건은 LLM CLI 를 여러 개 띄우므로, 요청을 받는 대로 돌리면
계정 한도와 PC 자원을 금방 쓴다. 나머지는 차례를 기다린다.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class Job:
    """작업 하나. `done`·`total` 은 작업이 스스로 올린다(`total` 은 모르면 None)."""

    job_id: str
    kind: str
    key: str
    """같은 일을 가리키는 값. 같은 `key` 가 안 끝났으면 새로 돌리지 않는다."""

    status: str = QUEUED
    done: int = 0
    total: int | None = None
    result: Any = None
    error: dict[str, str] | None = None

    @property
    def active(self) -> bool:
        return self.status in (QUEUED, RUNNING)


class JobBoard:
    """작업 표. `limits` 는 종류 → 동시 실행 수, `describe` 는 예외 → 돌려줄 오류."""

    def __init__(
        self,
        limits: Mapping[str, int],
        describe: Callable[[Exception], dict[str, str]],
    ) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._describe = describe
        self.stopping = threading.Event()
        """표가 닫히는 중인지. 언제 끝날지 모르는 작업은 이 값을 보고 스스로 멈춘다."""
        self._pools = {
            kind: ThreadPoolExecutor(max_workers=size, thread_name_prefix=f"job-{kind}")
            for kind, size in limits.items()
        }

    def submit(self, kind: str, key: str, work: Callable[[Job], Any]) -> Job:
        """작업을 맡기고 바로 돌려준다. 같은 `key` 가 진행 중이면 그 작업을 준다."""
        with self._lock:
            for job in self._jobs.values():
                if job.key == key and job.active:
                    return job
            job = Job(uuid4().hex[:12], kind, key)
            self._jobs[job.job_id] = job
        self._pools[kind].submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Callable[[Job], Any]) -> None:
        job.status = RUNNING
        try:
            job.result = work(job)
            job.status = DONE
        except Exception as exc:  # noqa: BLE001 — 실패도 결과다. 표에 남겨 호출자가 읽게 한다
            job.error = self._describe(exc)
            job.status = FAILED

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        """기다리는 작업은 버리고, 돌고 있는 작업에는 멈추라고 알린다.

        `stopping` 을 보지 않는 작업(채점)은 끝까지 돈다. 끝이 정해져 있고 이미 비용이 든 일이다.
        """
        self.stopping.set()
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
