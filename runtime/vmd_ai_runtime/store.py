from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .locks import store_lock


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ChatStore:
    """Chats under ~/.vmdai/chats (or ``root_dir``).

    Writes to a chat's manifest.json and to index.jsonl run under the
    store lock (locks.store_lock), because several runtimes may share the
    directory (§2f Writes, §7 Several runtimes). The default store shares
    ~/.vmdai/.store.lock with settings.json; a custom ``root_dir`` keeps its
    own lock file inside that directory.
    """

    def __init__(self, root_dir: str | None = None):
        self.root_dir = Path(root_dir or os.path.expanduser("~/.vmdai/chats"))
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root_dir / "index.jsonl"
        self.lock_root = self.root_dir.parent if root_dir is None else self.root_dir

    def chat_dir(self, chat_id: str) -> Path:
        return self.root_dir / chat_id

    def _chat_dir(self, chat_id: str) -> Path:
        # Kept for callers written before chat_dir became public.
        return self.chat_dir(chat_id)

    def exists(self, chat_id: str) -> bool:
        return bool(chat_id) and (self.chat_dir(chat_id) / "manifest.json").is_file()

    def create_chat(self, title_hint: str = "") -> str:
        chat_id = f"chat_{uuid.uuid4().hex[:12]}"
        chat_dir = self.chat_dir(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "chat_id": chat_id,
            "title": title_hint.strip() or "New Chat",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "message_count": 0,
        }
        with store_lock(self.lock_root):
            self._write_manifest(chat_id, manifest)
            (chat_dir / "events.jsonl").touch()
            self._append_index_row({"chat_id": chat_id, "title": manifest["title"], "updated_at": manifest["updated_at"]})
        return chat_id

    def append_events(self, chat_id: str, events: Iterable[Dict[str, Any]]) -> int:
        if not chat_id:
            return 0
        chat_dir = self.chat_dir(chat_id)
        if not chat_dir.exists():
            return 0
        events_path = chat_dir / "events.jsonl"
        count = 0
        with events_path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                count += 1
        self._touch_manifest(chat_id, delta_messages=count)
        return count

    def list_chats(self, limit: int = 30, offset: int = 0) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        latest: Dict[str, Dict[str, Any]] = {}
        with self.index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                chat_id = str(row.get("chat_id") or "")
                if not chat_id:
                    continue
                latest[chat_id] = row
        rows = sorted(latest.values(), key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        safe_offset = max(0, int(offset or 0))
        safe_limit = max(1, min(int(limit or 30), 200))
        return rows[safe_offset:safe_offset + safe_limit]

    def get_manifest(self, chat_id: str) -> Dict[str, Any] | None:
        """Return the manifest dict for a chat, or None if it doesn't exist."""
        if not chat_id:
            return None
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def read_events(self, chat_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        """Read persisted events from a chat's JSONL log.

        Returns at most *limit* events (most recent if the file has more).
        """
        events_path = self.chat_dir(chat_id) / "events.jsonl"
        if not events_path.exists():
            return []
        all_events: List[Dict[str, Any]] = []
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_events.append(json.loads(line))
                except Exception:
                    continue
        # Return the tail (most-recent events) if we exceed *limit*
        if len(all_events) > limit:
            return all_events[-limit:]
        return all_events

    def update_title(self, chat_id: str, title: str) -> None:
        """Update the display title for a chat."""
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return
        with store_lock(self.lock_root):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                return
            manifest["title"] = title.strip() or manifest.get("title", "New Chat")
            self._write_manifest(chat_id, manifest)

    def _touch_manifest(self, chat_id: str, delta_messages: int = 0) -> None:
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return
        with store_lock(self.lock_root):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                return
            manifest["updated_at"] = _now_iso()
            manifest["message_count"] = int(manifest.get("message_count") or 0) + int(delta_messages or 0)
            self._write_manifest(chat_id, manifest)
            self._append_index_row({
                "chat_id": chat_id,
                "title": manifest.get("title") or "New Chat",
                "updated_at": manifest["updated_at"],
                "message_count": manifest["message_count"],
            })

    # Callers hold the store lock; these two never take it themselves.

    def _write_manifest(self, chat_id: str, manifest: Dict[str, Any]) -> None:
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_index_row(self, row: Dict[str, Any]) -> None:
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
