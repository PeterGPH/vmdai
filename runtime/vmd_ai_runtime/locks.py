"""locks.py - advisory file locks shared by every runtime on this machine.

store_lock(root): an exclusive fcntl.flock on root/.store.lock around every
write to settings.json, a chat's manifest.json and index.jsonl (§2f Writes).
ChatLock(chat_dir): a non-blocking exclusive flock on chats/<id>/.lock held
while a session has that chat open (§2b Concurrency).

flock locks belong to an open file description, so two opens in one process
exclude each other too, and the OS drops them when the process dies (even on
SIGKILL). File descriptors from os.open are not inherited by child processes.
POSIX only; stdlib only; imports on Python 3.9.
"""
from __future__ import annotations

import errno
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

STORE_LOCK_NAME = ".store.lock"
CHAT_LOCK_NAME = ".lock"
_BUSY_ERRNOS = (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES)


@contextmanager
def store_lock(root: Path) -> Iterator[None]:
    """Hold the exclusive store lock for the duration of the ``with`` block.

    Never nest two store_lock blocks for the same root in one thread: the
    second open would wait for the first forever.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(root / STORE_LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


class ChatLock:
    """Exclusive, non-blocking lock on chats/<id>/.lock."""

    def __init__(self, chat_dir: Path) -> None:
        self.path = Path(chat_dir) / CHAT_LOCK_NAME
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """Take the lock; False when another holder (process or object) has it."""
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in _BUSY_ERRNOS:
                return False
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
