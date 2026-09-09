"""Small local-file write primitives; no network work while holding these locks.

All read/modify/write callers must acquire locked_paths *before* reading.
A surviving output journal blocks another write instead of guessing recovery.
Readers that do not take these locks can still observe a multi-file transition.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

_LOCKS: dict[str, FileLock] = {}
_LOCKS_GUARD = threading.Lock()


def _canonical(path: Path) -> Path:
    return Path(os.path.normcase(str(path.resolve())))


def _lock_for(path: Path) -> FileLock:
    canonical = _canonical(path)
    key = str(canonical)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = FileLock(str(canonical.with_name(f".{canonical.name}.write.lock")))
            _LOCKS[key] = lock
        return lock


@contextmanager
def locked_paths(paths: Iterable[Path]) -> Iterator[None]:
    """Cross-process, thread-local-reentrant locks, always in canonical order."""
    ordered = sorted({_canonical(path) for path in paths}, key=str)
    with ExitStack() as stack:
        for path in ordered:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                stack.enter_context(_lock_for(path).acquire(timeout=0))
            except Timeout as exc:
                raise RuntimeError(f"已有正式写入任务占用文件，未执行覆盖：{path}") from exc
        yield


def _sync_directory(directory: Path) -> None:
    # Windows does not support opening a directory for fsync through os.open.
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def atomic_write_bytes(path: Path, content: bytes) -> None:
    with locked_paths((path,)):
        temporary = stage_bytes(path, content)
        try:
            os.replace(temporary, path)
            _sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)


def require_no_pending_transaction(journal: Path) -> None:
    if journal.exists():
        raise RuntimeError(
            f"发现未完成的正式输出事务，拒绝继续覆盖：{journal}；"
            "请先核对事务记录及备份，不能直接删除标记后重跑"
        )


def atomic_write_many(values: Mapping[Path, bytes | None], *, journal: Path) -> None:
    """Stage all files, durably record recovery metadata, then replace.

    Catchable failures restore only paths that were actually touched.  A hard
    crash or failed rollback leaves the journal and backups for investigation.
    This is recoverable replacement, not simultaneous filesystem visibility.
    """
    if not values:
        return
    if len({_canonical(path) for path in values}) != len(values):
        raise ValueError("输出目标路径存在别名重复")
    if _canonical(journal) in {_canonical(path) for path in values}:
        raise ValueError("事务日志不能覆盖输出目标")
    with locked_paths((*values, journal)):
        require_no_pending_transaction(journal)
        originals = {path: path.read_bytes() if path.exists() else None for path in values}
        changes = {path: value for path, value in values.items() if value != originals[path]}
        if not changes:
            return
        staged: dict[Path, Path] = {}
        backups: dict[Path, Path] = {}
        touched: list[Path] = []
        prepared = False
        commit_ready = False
        keep_recovery = False
        try:
            # Incremental assignment ensures that partial staging is cleaned up.
            for path, content in changes.items():
                if content is not None:
                    staged[path] = stage_bytes(path, content)
                original = originals[path]
                if original is not None:
                    backups[path] = stage_bytes(path, original)
            for directory in {path.parent for path in changes}:
                _sync_directory(directory)
            metadata = {
                "version": 1,
                "state": "prepared",
                "files": [
                    {
                        "path": str(_canonical(path)),
                        "backup": str(backups[path]) if path in backups else None,
                        "staged": str(staged[path]) if path in staged else None,
                        "old_sha256": hashlib.sha256(originals[path]).hexdigest()
                        if originals[path] is not None else None,
                        "new_sha256": hashlib.sha256(content).hexdigest() if content is not None else None,
                    }
                    for path, content in changes.items()
                ],
            }
            atomic_write_bytes(journal, (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode())
            prepared = True
            for path, content in changes.items():
                # Record before replacement, including the tiny signal window.
                touched.append(path)
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(staged[path], path)
            for directory in {path.parent for path in changes}:
                _sync_directory(directory)
            commit_ready = True
            journal.unlink()
            _sync_directory(journal.parent)
            prepared = False
        except BaseException as original_error:
            if commit_ready:
                # All replacements finished. Never attempt rollback after the
                # journal may have disappeared: a second rollback failure would
                # otherwise leave mixed files without any blocking marker.
                keep_recovery = journal.exists()
                raise RuntimeError(
                    "正式输出已完整替换，但事务标记清理或目录同步失败；"
                    f"请核对输出与事务记录：{journal}"
                ) from original_error
            if not prepared and journal.exists():
                keep_recovery = True
            rollback_errors: list[str] = []
            for path in reversed(touched):
                try:
                    if originals[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        os.replace(backups[path], path)
                    _sync_directory(path.parent)
                except Exception as rollback_error:
                    rollback_errors.append(f"{path}: {rollback_error}")
            if rollback_errors:
                keep_recovery = True
                raise RuntimeError(
                    f"正式输出失败且回滚未完成，保留事务证据 {journal}：{'；'.join(rollback_errors)}"
                ) from original_error
            if prepared:
                try:
                    journal.unlink(missing_ok=True)
                    _sync_directory(journal.parent)
                except Exception:
                    keep_recovery = True
            raise
        finally:
            if not keep_recovery:
                for temporary in (*staged.values(), *backups.values()):
                    temporary.unlink(missing_ok=True)
