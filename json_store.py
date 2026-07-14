"""Small, cross-process-safe helpers for JSON-backed application data."""

from __future__ import annotations

import copy
import errno
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - exercised on POSIX CI
    import fcntl


class JsonStoreError(RuntimeError):
    """Raised when an existing JSON file cannot be safely read or written."""


_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_WINDOWS_REPLACE_RETRY_DELAYS = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32)
_WINDOWS_REPLACE_RETRY_WINERRORS = frozenset({5, 32, 33})


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


def _thread_lock(path: Path) -> threading.RLock:
    key = _path_key(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


def read_json(path: str | os.PathLike[str], default: Any) -> Any:
    """Read JSON, using an independent default only when the file is absent."""

    target = Path(path).expanduser().resolve()
    try:
        with target.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JsonStoreError(f"Unable to read JSON file {target}: {exc}") from exc


def _replace_with_retry(source: str, target: Path) -> None:
    """Retry transient Windows sharing failures without hiding permanent errors."""

    for attempt in range(len(_WINDOWS_REPLACE_RETRY_DELAYS) + 1):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            retryable = os.name == "nt" and (
                exc.errno == errno.EACCES
                or getattr(exc, "winerror", None)
                in _WINDOWS_REPLACE_RETRY_WINERRORS
            )
            if not retryable or attempt == len(_WINDOWS_REPLACE_RETRY_DELAYS):
                raise
            time.sleep(_WINDOWS_REPLACE_RETRY_DELAYS[attempt])


def write_json_atomic(path: str | os.PathLike[str], data: Any) -> None:
    """Write JSON through a same-directory temporary file and atomic replace."""

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    fd: int | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = None
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _replace_with_retry(temp_name, target)
        temp_name = None
    except Exception as exc:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if isinstance(exc, JsonStoreError):
            raise
        raise JsonStoreError(f"Unable to write JSON file {target}: {exc}") from exc


def _acquire_platform_lock(fd: int) -> None:
    if os.name == "nt":
        retryable = {errno.EACCES, errno.EAGAIN, errno.EDEADLK, 13}
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in retryable:
                    raise
                time.sleep(0.01)
    else:  # pragma: no cover - exercised on POSIX CI
        fcntl.flock(fd, fcntl.LOCK_EX)


def _release_platform_lock(fd: int) -> None:
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - exercised on POSIX CI
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        # The operating system releases a process lock on exit. Do not mask
        # the operation's original exception while cleaning up.
        pass


@contextmanager
def _file_lock(path: Path):
    """Hold a stable sidecar lock for one JSON path."""

    lock = _thread_lock(path)
    with lock:
        lock_path = Path(f"{path}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        acquired = False
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
            _acquire_platform_lock(fd)
            acquired = True
            yield
        finally:
            if acquired:
                _release_platform_lock(fd)
            os.close(fd)


def locked_update_json(
    path: str | os.PathLike[str],
    default: Any,
    updater: Callable[[Any], Any],
) -> Any:
    """Lock, read, update, and atomically replace a JSON document.

    ``updater`` may mutate the loaded value and return ``None`` or return a
    replacement value. Equal values are treated as a no-op and are not written.
    """

    target = Path(path).expanduser().resolve()
    with _file_lock(target):
        current = read_json(target, default)
        original = copy.deepcopy(current)
        replacement = updater(current)
        if replacement is None:
            replacement = current
        if replacement != original:
            write_json_atomic(target, replacement)
        return replacement


__all__ = ["JsonStoreError", "read_json", "write_json_atomic", "locked_update_json"]
