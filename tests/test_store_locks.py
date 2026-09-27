"""P03-T03: store lock, per-chat lock, public chat_dir (§2b Concurrency, §2f Writes, §7)."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from vmd_ai_runtime.locks import ChatLock
from vmd_ai_runtime.store import ChatStore

RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"

CHAT_HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from vmd_ai_runtime.locks import ChatLock
lock = ChatLock(Path(sys.argv[2]))
print("held" if lock.acquire() else "busy", flush=True)
time.sleep(60)
"""

STORE_HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from vmd_ai_runtime.locks import store_lock
with store_lock(Path(sys.argv[2])):
    print("locked", flush=True)
    time.sleep(float(sys.argv[3]))
"""


def _spawn(script, *args):
    proc = subprocess.Popen([sys.executable, "-c", script, str(RUNTIME_DIR)] + [str(a) for a in args],
                            stdout=subprocess.PIPE, text=True)
    return proc, proc.stdout.readline().strip()


def test_chat_lock_exclusive_across_processes(tmp_path):
    proc, line = _spawn(CHAT_HOLDER, tmp_path)
    try:
        assert line == "held"
        mine = ChatLock(tmp_path)
        assert mine.acquire() is False and mine.held is False
    finally:
        proc.kill()
        proc.wait(5)


def test_chat_lock_released_on_kill(tmp_path):
    """Review focus: the OS frees the per-chat lock when the holder is SIGKILLed."""
    proc, line = _spawn(CHAT_HOLDER, tmp_path)
    try:
        assert line == "held"
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(5)
        mine = ChatLock(tmp_path)
        assert mine.acquire() is True and mine.held is True
        other = ChatLock(tmp_path)
        assert other.acquire() is False            # exclusive inside one process too
        mine.release()
        assert mine.held is False and other.acquire() is True
        other.release()
        assert (tmp_path / ".lock").exists()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(5)


def test_store_lock_serialises_index_appends(tmp_path):
    store = ChatStore(root_dir=str(tmp_path / "chats"))
    assert store.lock_root == tmp_path / "chats"
    chat_id = store.create_chat("t")
    proc, line = _spawn(STORE_HOLDER, store.lock_root, 0.8)
    try:
        assert line == "locked"
        t0 = time.monotonic()
        store.append_events(chat_id, [{"role": "user", "type": "message", "text": "hi", "metadata": {}}])
        assert time.monotonic() - t0 >= 0.4          # waited for the other process
    finally:
        proc.wait(5)

    def touch():
        for _ in range(40):
            store.append_events(chat_id, [{"role": "assistant", "type": "chunk", "text": "x", "metadata": {}}])

    threads = [threading.Thread(target=touch) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = [json.loads(line) for line in store.index_path.read_text(encoding="utf-8").splitlines()]
    assert store.get_manifest(chat_id)["message_count"] == 161    # no lost read-modify-write
    assert rows[-1]["message_count"] == 161


def test_create_chat_unchanged_for_legacy_callers(tmp_path):
    store = ChatStore(root_dir=str(tmp_path))
    chat_id = store.create_chat("My chat")
    assert re.match(r"^chat_[0-9a-f]{12}$", chat_id)
    assert store.chat_dir(chat_id) == tmp_path / chat_id == store._chat_dir(chat_id)
    assert store.exists(chat_id)
    assert not store.exists("chat_000000000000") and not store.exists("")
    manifest = store.get_manifest(chat_id)
    assert set(manifest) == {"chat_id", "title", "created_at", "updated_at", "message_count"}
    assert manifest["title"] == "My chat" and manifest["message_count"] == 0
    assert (store.chat_dir(chat_id) / "events.jsonl").read_text() == ""
    assert json.loads(store.index_path.read_text().splitlines()[0])["chat_id"] == chat_id
    assert store.append_events(None, [{"role": "user"}]) == 0
    assert ChatStore().lock_root == Path(os.path.expanduser("~/.vmdai"))   # the hermetic HOME
