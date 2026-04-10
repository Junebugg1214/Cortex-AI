from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_LOCK_REGISTRY: dict[str, threading.RLock] = {}
_LOCK_REGISTRY_GUARD = threading.Lock()


def _normalized_lock_key(path: Path) -> str:
    return str(path.expanduser().resolve())


def _lock_for(path: Path) -> threading.RLock:
    key = _normalized_lock_key(path)
    with _LOCK_REGISTRY_GUARD:
        lock = _LOCK_REGISTRY.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCK_REGISTRY[key] = lock
        return lock


@contextmanager
def locked_path(path: Path) -> Iterator[Path]:
    lock = _lock_for(path)
    lock.acquire()
    try:
        yield path
    finally:
        lock.release()


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    temp_path = Path(raw_temp_path)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "locked_path",
]
