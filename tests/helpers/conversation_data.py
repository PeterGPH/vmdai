"""Message builders for the conversation-memory tests (plan 03).

Messages use the loop's Anthropic-style shape. Tool ids follow the canonical
form the loop writes to messages_out: ``call_<call_key>``.
"""
from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from vmd_ai_runtime.conversation import Appender


def tiny_png(width: int, height: int) -> bytes:
    """A valid 8-bit RGB PNG of the given size (all black)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def user(text: str) -> Dict[str, Any]:
    return {"role": "user", "content": text}


def assistant_text(text: str) -> Dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def assistant_tools(text: str, *calls: Tuple[str, str, Dict[str, Any]]) -> Dict[str, Any]:
    """An assistant turn with optional text and one tool_use per (call_key, name, input)."""
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    for call_key, name, tool_input in calls:
        content.append({"type": "tool_use", "id": "call_" + call_key, "name": name, "input": tool_input})
    return {"role": "assistant", "content": content}


def tool_results(*results: Tuple[str, bool, str]) -> Dict[str, Any]:
    """A tool-results message with one tool_result per (call_key, ok, text)."""
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "call_" + call_key, "content": text, "is_error": not ok}
        for call_key, ok, text in results
    ]}


def image_block(png: bytes) -> Dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.b64encode(png).decode("ascii")}}


def snapshot_result(call_key: str, png: bytes, text: str = "Snapshot captured.") -> Dict[str, Any]:
    """A tool-results message for capture_vmd_snapshot carrying an inline image."""
    return {"role": "user", "content": [{
        "type": "tool_result",
        "tool_use_id": "call_" + call_key,
        "content": [{"type": "text", "text": text}, image_block(png)],
        "is_error": False,
    }]}


def write_exchange(chat_dir: Path, request_id: str, messages: Sequence[Dict[str, Any]]) -> None:
    """Append one exchange to chat_dir/messages.jsonl the way the loop would."""
    appender = Appender(chat_dir, request_id, clock=lambda: 1000.0)
    for message in messages:
        appender.append(message)


def tool_pairs_ok(messages: Sequence[Dict[str, Any]]) -> bool:
    """True when every tool_use is answered by the next message and every
    tool_result follows the assistant turn that asked for it."""
    for index, message in enumerate(messages):
        content = message.get("content")
        blocks = content if isinstance(content, list) else []
        uses = [b["id"] for b in blocks if b.get("type") == "tool_use"]
        results = [b["tool_use_id"] for b in blocks if b.get("type") == "tool_result"]
        if results:
            previous = messages[index - 1].get("content") if index > 0 else None
            asked = {b.get("id") for b in (previous if isinstance(previous, list) else [])
                     if b.get("type") == "tool_use"}
            if not set(results) <= asked:
                return False
        if uses:
            following = messages[index + 1].get("content") if index + 1 < len(messages) else None
            answered = {b.get("tool_use_id") for b in (following if isinstance(following, list) else [])
                        if b.get("type") == "tool_result"}
            if set(uses) - answered:
                return False
    return True
