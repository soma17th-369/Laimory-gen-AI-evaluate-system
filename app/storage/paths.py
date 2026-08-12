"""data/ 경로 규칙 — 폴더 구조의 **유일한 정본**.

다른 코드는 여기 함수만 쓰고 경로 문자열을 직접 조합하지 않는다. 구조가 바뀌면 여기만 고친다.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import get_settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(name: str) -> str:
    """파일/폴더명에 안전하지 않은 문자를 치환(경로 탈출 방지)."""
    cleaned = _SAFE.sub("_", (name or "").strip())
    return cleaned or "unnamed"


def data_root() -> Path:
    return Path(get_settings().data_dir)


def collection_file() -> Path:
    """대시보드용 수집 스냅샷(트레이스 요약 목록). 집계의 원천."""
    return data_root() / "collection.json"


def tasks_dir() -> Path:
    return data_root() / "tasks"


def task_dir(task_id: str) -> Path:
    return tasks_dir() / _safe(task_id)


def task_trace_file(task_id: str) -> Path:
    return task_dir(task_id) / "trace.json"


def task_prompts_file(task_id: str) -> Path:
    return task_dir(task_id) / "prompts.json"


def evaluations_dir() -> Path:
    return data_root() / "evaluations"


def evaluation_file(task_id: str) -> Path:
    return evaluations_dir() / f"{_safe(task_id)}.json"


def improvements_dir() -> Path:
    return data_root() / "improvements"


def improvement_file(slug: str) -> Path:
    return improvements_dir() / f"{_safe(slug)}.json"


def testdata_dir(kind: str) -> Path:
    """kind: 'from-improvement' | 'from-logs'."""
    return data_root() / "testdata" / _safe(kind)


def testdata_file(kind: str, slug: str) -> Path:
    return testdata_dir(kind) / f"{_safe(slug)}.json"
