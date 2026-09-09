"""Small file transactions: stable process locks and recoverable TXT publication.

A cache update is deliberately independent of a successfully published TXT batch.
Always hold locked_paths across the entire read/modify/write, not just replace().
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

_LOCKS: dict[str, FileLock] = {}
_LOCKS_GUARD = threading.Lock()


def path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


@contextmanager
def locked_paths(paths, *, timeout: float = 0) -> Iterator[None]:
    """Fail fast on concurrent writers; locks are reentrant in the owner thread."""
    keys = sorted({path_key(Path(path)) for path in paths})
    with ExitStack() as stack:
        for key in keys:
            path = Path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            with _LOCKS_GUARD:
                lock = _LOCKS.setdefault(key, FileLock(str(path.with_name('.' + path.name + '.lock'))))
            try:
                stack.enter_context(lock.acquire(timeout=timeout))
            except Timeout as exc:
                raise RuntimeError(f'已有正式写入任务占用文件，未覆盖：{path}') from exc
        yield


def _sync_directory(path: Path) -> None:
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _stage_bytes(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = _stage_bytes(path, payload)
    try:
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _pending_transaction(paths: tuple[Path, ...]) -> Path | None:
    keys = {path_key(path) for path in paths}
    for parent in {path.parent for path in paths}:
        for journal in parent.glob('.zodiac-txn-*.json'):
            try:
                entries = json.loads(journal.read_text(encoding='utf-8'))['files']
                affected = {path_key(Path(entry['path'])) for entry in entries}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise RuntimeError(f'事务标记损坏，拒绝继续覆盖：{journal}') from exc
            if keys & affected:
                return journal
    return None


def recover_transaction(journal: Path) -> None:
    """Explicit recovery only. Never silently overwrite a later unrelated write."""
    manifest = json.loads(journal.read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('不支持的事务标记')
    entries = manifest['files']
    paths = tuple(Path(entry['path']) for entry in entries)
    with locked_paths(paths):
        restored: list[tuple[Path, bytes | None]] = []
        for entry, path in zip(entries, paths):
            backup = entry['backup']
            payload = Path(backup).read_bytes() if backup is not None else None
            digest = hashlib.sha256(payload).hexdigest() if payload is not None else None
            if digest != entry['old_sha256']:
                raise ValueError(f'事务备份哈希不一致：{path}')
            current = path.read_bytes() if path.exists() else None
            current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
            if current_hash not in {entry['old_sha256'], entry['new_sha256']}:
                raise ValueError(f'目标文件已有其他更新，禁止自动恢复：{path}')
            restored.append((path, payload))
        for path, payload in restored:
            if payload is None:
                path.unlink(missing_ok=True)
                _sync_directory(path.parent)
            else:
                atomic_write_bytes(path, payload)
        for parent in {path.parent for path in paths}:
            (parent / journal.name).unlink(missing_ok=True)
            _sync_directory(parent)
        for entry in entries:
            if entry['backup'] is not None:
                Path(entry['backup']).unlink(missing_ok=True)


def atomic_batch_write(payloads: Mapping[Path, bytes | None]) -> None:
    """Publish bounded local files, retaining recovery evidence after a hard kill."""
    if not payloads:
        return
    paths = tuple(Path(path).resolve() for path in payloads)
    if len({path_key(path) for path in paths}) != len(paths):
        raise ValueError('事务目标路径重复')
    values = dict(zip(paths, payloads.values()))
    with locked_paths(paths):
        pending = _pending_transaction(paths)
        if pending is not None:
            raise RuntimeError(f'发现未完成事务，先检查并恢复，禁止覆盖：{pending}')
        originals = {path: path.read_bytes() if path.exists() else None for path in paths}
        txid = uuid.uuid4().hex
        journals = tuple(parent / f'.zodiac-txn-{txid}.json' for parent in sorted({path.parent for path in paths}, key=str))
        staged: dict[Path, Path] = {}
        backups: list[Path] = []
        replaced: list[Path] = []
        entries = []
        keep_evidence = False
        try:
            for path, payload in values.items():
                old = originals[path]
                backup = path.with_name(f'.{path.name}.{txid}.bak') if old is not None else None
                if backup is not None:
                    atomic_write_bytes(backup, old)
                    backups.append(backup)
                if payload is not None:
                    staged[path] = _stage_bytes(path, payload)
                entries.append({
                    'path': str(path), 'backup': str(backup) if backup is not None else None,
                    'old_sha256': hashlib.sha256(old).hexdigest() if old is not None else None,
                    'new_sha256': hashlib.sha256(payload).hexdigest() if payload is not None else None,
                })
            manifest = json.dumps({'version': 1, 'files': entries}, ensure_ascii=False).encode('utf-8')
            for journal in journals:
                atomic_write_bytes(journal, manifest)
            for path, payload in values.items():
                if payload is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(staged[path], path)
                replaced.append(path)
                _sync_directory(path.parent)
            for journal in journals:
                journal.unlink()
                _sync_directory(journal.parent)
        except BaseException:
            try:
                for path in reversed(replaced):
                    original = originals[path]
                    if original is None:
                        path.unlink(missing_ok=True)
                        _sync_directory(path.parent)
                    else:
                        atomic_write_bytes(path, original)
                for journal in journals:
                    journal.unlink(missing_ok=True)
            except BaseException:
                keep_evidence = True
            raise
        finally:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)
            if not keep_evidence:
                for backup in backups:
                    backup.unlink(missing_ok=True)
