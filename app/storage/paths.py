"""data/ 경로 규칙 — 폴더 구조의 **유일한 정본**.

다른 코드는 여기 함수만 쓰고 경로 문자열을 직접 조합하지 않는다. 구조가 바뀌면 여기만 고친다.

LangFuse 프로젝트(dev·prod)는 **경로로 가르지 않는다**(→ [app.environments][]). 어느 프로젝트에서
온 것인지는 데이터 안의 `env` 필드가 들고 있고, 화면은 한 목록에 시간순으로 늘어놓는다. 트레이스
id 와 taskId 가 전역 유일(UUIDv7·32자리 hex)이라 파일명이 부딪히지 않는다.

환경별로 갈리는 것은 **동기화 커서 하나**뿐이고, 그것도 `collection.state.json` 안에서 환경을
키로 나눠 담는다.
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
    """누적 수집된 트레이스 요약 목록. 집계의 원천이며 교체가 아니라 병합으로 쌓인다."""
    return data_root() / "collection.json"


def collection_state_file() -> Path:
    """증분 동기화 커서(연속으로 훑은 구간의 끝·마지막 동기화 시각·저장 건수)."""
    return data_root() / "collection.state.json"


def generation_rollup_file() -> Path:
    """traceId → 모델·토큰 롤업 캐시. 트레이스 목록 API 에 없는 정보만 모아둔다."""
    return data_root() / "generations.json"


def tasks_dir() -> Path:
    return data_root() / "tasks"


def task_dir(task_id: str) -> Path:
    return tasks_dir() / _safe(task_id)


def task_trace_file(task_id: str) -> Path:
    return task_dir(task_id) / "trace.json"


def task_prompts_file(task_id: str) -> Path:
    return task_dir(task_id) / "prompts.json"


def prompts_dir() -> Path:
    """편집 가능한 프롬프트의 버전 레지스트리 루트."""
    return data_root() / "prompts"


def prompt_dir(name: str) -> Path:
    """이름별 버전 폴더. 예: data/prompts/judge-rubric/."""
    return prompts_dir() / _safe(name)


def prompt_version_file(name: str, version: int) -> Path:
    return prompt_dir(name) / f"v{int(version)}.json"


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
