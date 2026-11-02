"""json 저장/로드/목록 유틸. 한글은 그대로(ensure_ascii=False), 부모 폴더는 자동 생성.

저장은 **원자적**이다. 임시 파일에 다 쓴 뒤 교체하므로, 쓰는 도중 프로세스가 죽거나 다른 프로세스가
읽어도 언제나 완전한 파일만 보인다.

읽고-합쳐-쓰는 저장은 원자적 쓰기만으로 부족하다. 두 프로세스가 같은 내용을 읽고 각자 합쳐 쓰면
나중에 쓴 쪽이 먼저 쓴 쪽을 지운다. 화면과 MCP 서버는 별도 프로세스이므로 그런 곳은
[locked][app.storage.store.locked] 로 감싼다.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar
from uuid import uuid4

from filelock import FileLock

LOCK_TIMEOUT_SECONDS = 60.0
"""잠금을 기다리는 최대 시간. 저장 순간에만 잡는 잠금이라 이보다 오래 막히면 이상이 있는 것이다."""

_SHARING_RETRIES = 40
_SHARING_WAIT_SECONDS = 0.05
"""파일을 다른 프로세스가 잡고 있을 때 다시 시도하는 횟수와 간격(합계 2초)."""

_T = TypeVar("_T")


class CorruptJson(ValueError):
    """파일은 있는데 json 으로 읽을 수 없을 때."""


def _retry_while_shared(call: Callable[[], _T]) -> _T:
    """Windows 에서는 다른 프로세스가 파일을 여는 순간 교체·열기가 PermissionError 로 실패한다.

    파일 내용 문제가 아니라 잠깐 겹친 것이므로 짧게 기다렸다가 다시 부른다.
    """
    for _ in range(_SHARING_RETRIES):
        try:
            return call()
        except PermissionError:
            time.sleep(_SHARING_WAIT_SECONDS)
    return call()


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """`path` 를 읽고-합쳐-쓰는 동안 다른 프로세스·스레드를 기다리게 한다.

    잠금은 `<path>.lock` 파일에 OS 잠금으로 건다. 프로세스가 죽으면 OS 가 풀어 주므로 남아서 막지
    않는다. 같은 `path` 를 안쪽에서 다시 잠그면 자기 자신을 기다리므로 겹쳐 쓰지 않는다.
    """
    lock_file = path.with_name(f"{path.name}.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(lock_file, timeout=LOCK_TIMEOUT_SECONDS):
        yield


def save_json(path: Path, data: Any) -> Path:
    """dict/list(또는 pydantic model_dump 결과)를 json 으로 저장. 부모 폴더 생성."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        _retry_while_shared(lambda: os.replace(temporary, path))
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read_json(path: Path) -> Any | None:
    """없으면 None, 깨졌으면 [CorruptJson][app.storage.store.CorruptJson].

    읽어서 합친 뒤 다시 쓰는 곳은 이걸 쓴다. 깨진 파일을 빈 값으로 읽으면 그 위에 덮어써 기록이 사라진다.
    """
    try:
        text = _retry_while_shared(lambda: path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise CorruptJson(f"{path.name} 을 읽을 수 없습니다: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptJson(f"{path.name} 을 읽을 수 없습니다: {exc}") from exc


def load_json(path: Path) -> Any | None:
    """없으면 None. 깨진 json 도 None(호출부가 판단)."""
    try:
        return read_json(path)
    except (CorruptJson, OSError):
        return None


def list_json(directory: Path) -> list[Path]:
    """디렉터리 안의 *.json 경로 목록(이름순). 없으면 빈 리스트."""
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.json") if p.is_file())
