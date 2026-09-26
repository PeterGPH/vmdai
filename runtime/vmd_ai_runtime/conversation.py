"""conversation.py - the per-chat canonical message log (chats/<id>/messages.jsonl).

Spec §2b and C5. One JSON object per line, append-only, never rewritten:

  {"v":1,"kind":"message","request_id":...,"ts":...,"message":{"role":...,"content":...}}
  {"v":1,"kind":"late_result","request_id":...,"ts":...,"call_key":...,"ok":...,
   "executed":"yes|no|unknown","output":...,"error":...}

The loop hands the Appender canonical copies (tool ids already rewritten to
``call_<call_key>``). The Appender replaces each base64 image with an
``image_ref`` block backed by ``images/<call_key>.png`` (it writes the file
only when the bridge has not) and caps each tool result's output section at
STORE_OUTPUT_CAP characters, leaving C3's failure lines, the C5 note and the
C4 nudge intact. Readers skip lines they do not understand. Stdlib only;
imports on 3.9.
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import logging
import re
import struct
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("vmdai.conversation")

CHARS_PER_TOKEN = 3.5
STORE_OUTPUT_CAP = 6000
STORE_WARN_BYTES = 2 * 1024 * 1024
MESSAGES_FILE = "messages.jsonl"
LINE_VERSION = 1
KNOWN_KINDS = ("message", "late_result")
# Lines that follow a tool's own output and are never cut: the C5 truncation
# note, the executor's 1 MB note and the C4 loop-guard nudge.
TAIL_MARKERS = ("[output truncated:", "[executor limit:", "Loop check:")
# C3's structured failure text (result_format "structured", plan 05's
# _structured_summary) starts with FAILURE_HEAD_PREFIX and puts the tool's
# own output after an OUTPUT_START_LINE line. The failure lines up to and
# including that line are outside the store cap too (C5 Memory).
FAILURE_HEAD_PREFIX = "Failed at statement "
OUTPUT_START_LINE = "Output before the error:"

_WRITE_LOCK = threading.Lock()
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def messages_path(chat_dir: Path) -> Path:
    """Path of a chat's canonical message log."""
    return Path(chat_dir) / MESSAGES_FILE


def split_output_section(text: str) -> Tuple[str, str]:
    """Split a tool-result text into (output section, tail).

    The tail starts at the first line after the first one that begins with a
    TAIL_MARKERS prefix and keeps its leading newline, so output + tail == text.
    """
    text = str(text or "")
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].lstrip().startswith(TAIL_MARKERS):
            return "\n".join(lines[:index]), "\n" + "\n".join(lines[index:])
    return text, ""


def _split_failure_head(body: str) -> Tuple[str, str]:
    """(C3 failure lines, tool output) of an output section; ("", body) otherwise."""
    marker = "\n" + OUTPUT_START_LINE + "\n"
    if not body.startswith(FAILURE_HEAD_PREFIX) or marker not in body:
        return "", body
    cut = body.index(marker) + len(marker)
    return body[:cut], body[cut:]


def cap_output_section(text: str, cap: int = STORE_OUTPUT_CAP) -> str:
    """Cap only the output section at ``cap`` characters (head plus tail).

    C3's failure lines in front of the output, and the C5 note and C4 nudge
    after it, are neither counted nor cut.
    """
    text = str(text or "")
    body, tail = split_output_section(text)
    failure_head, output = _split_failure_head(body)
    if len(output) <= cap:
        return text
    head_len = cap // 2
    tail_len = cap - head_len
    marker = "\n[stored copy cut: %d chars omitted]\n" % (len(output) - cap)
    return failure_head + output[:head_len] + marker + output[len(output) - tail_len:] + tail


def _call_key_from_id(tool_use_id: Any) -> str:
    raw = str(tool_use_id or "")
    if raw.startswith("call_"):
        raw = raw[len("call_"):]
    return _UNSAFE_KEY_CHARS.sub("_", raw)[:64] or "unknown"


def _image_size(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    if len(data) >= 24 and data[:8] == _PNG_MAGIC:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    return None, None


class Appender:
    """Writes one messages.jsonl line per appended message (§2b Writes).

    ``ctx.messages_out`` is duck-typed: the loop only calls ``append``.
    """

    def __init__(self, chat_dir: Path, request_id: str, *,
                 clock: Callable[[], float] = time.time) -> None:
        self.chat_dir = Path(chat_dir)
        self.request_id = str(request_id)
        self._clock = clock
        self._warned = False

    def append(self, message: Dict[str, Any]) -> None:
        self._write({
            "v": LINE_VERSION,
            "kind": "message",
            "request_id": self.request_id,
            "ts": self._clock(),
            "message": self._stored_message(message),
        })

    def append_late_result(self, call_key: str, ok: bool, executed: str,
                           output: str, error: str) -> None:
        self._write({
            "v": LINE_VERSION,
            "kind": "late_result",
            "request_id": self.request_id,
            "ts": self._clock(),
            "call_key": str(call_key),
            "ok": bool(ok),
            "executed": str(executed or "unknown"),
            "output": cap_output_section(str(output or "")),
            "error": str(error or ""),
        })

    # -- internals -------------------------------------------------------

    def _write(self, line: Dict[str, Any]) -> None:
        data = (json.dumps(line, ensure_ascii=True) + "\n").encode("ascii")
        path = messages_path(self.chat_dir)
        with _WRITE_LOCK:
            self.chat_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "ab") as handle:
                handle.write(data)
                handle.flush()
            size = path.stat().st_size
        if size >= STORE_WARN_BYTES and not self._warned:
            self._warned = True
            logger.warning("messages.jsonl of %s is %.1f MB (over 2 MB)",
                           self.chat_dir.name, size / (1024.0 * 1024.0))

    def _stored_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        out = {key: copy.deepcopy(value) for key, value in message.items() if key != "content"}
        content = message.get("content")
        if not isinstance(content, list):
            out["content"] = copy.deepcopy(content)
            return out
        blocks: List[Any] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append(self._stored_tool_result(block))
            elif isinstance(block, dict) and block.get("type") == "image":
                blocks.append(self._stored_image(block, None, 0))
            else:
                blocks.append(copy.deepcopy(block))
        out["content"] = blocks
        return out

    def _stored_tool_result(self, block: Dict[str, Any]) -> Dict[str, Any]:
        out = {key: copy.deepcopy(value) for key, value in block.items() if key != "content"}
        key = _call_key_from_id(block.get("tool_use_id"))
        content = block.get("content")
        if isinstance(content, str):
            out["content"] = cap_output_section(content)
            return out
        if not isinstance(content, list):
            out["content"] = copy.deepcopy(content)
            return out
        parts: List[Any] = []
        image_index = 0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                capped = dict(part)
                capped["text"] = cap_output_section(str(part.get("text") or ""))
                parts.append(capped)
            elif isinstance(part, dict) and part.get("type") == "image":
                parts.append(self._stored_image(part, key, image_index))
                image_index += 1
            else:
                parts.append(copy.deepcopy(part))
        out["content"] = parts
        return out

    def _stored_image(self, block: Dict[str, Any], key: Optional[str], index: int) -> Dict[str, Any]:
        source = block.get("source") or {}
        if source.get("type") != "base64":
            return copy.deepcopy(block)
        try:
            data = base64.b64decode(str(source.get("data") or ""))
        except (binascii.Error, ValueError, TypeError):
            return {"type": "text", "text": "[snapshot could not be stored]"}
        media_type = str(source.get("media_type") or "image/png")
        ext = "jpg" if media_type in ("image/jpeg", "image/jpg") else "png"
        if key is None:
            key = "img_" + hashlib.sha1(data).hexdigest()[:12]
        name = "%s.%s" % (key, ext) if index == 0 else "%s_%d.%s" % (key, index + 1, ext)
        target = self.chat_dir / "images" / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        width, height = _image_size(data)
        return {"type": "image_ref", "path": "images/" + name,
                "media_type": media_type, "width": width, "height": height}


def read_lines(chat_dir: Path) -> List[Dict[str, Any]]:
    """Every line of messages.jsonl this runtime understands, in file order.

    Lines that do not decode, and lines with an unknown ``kind``, are skipped
    with a warning (a crash mid-write leaves a truncated last line).
    """
    path = messages_path(chat_dir)
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "rb") as handle:
        for number, raw in enumerate(handle, start=1):
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                line = json.loads(text)
            except ValueError:
                logger.warning("%s line %d does not decode; skipped", path, number)
                continue
            kind = line.get("kind") if isinstance(line, dict) else None
            if kind not in KNOWN_KINDS:
                logger.warning("%s line %d has unknown kind %r; skipped", path, number, kind)
                continue
            if kind == "message" and not isinstance(line.get("message"), dict):
                logger.warning("%s line %d has no message object; skipped", path, number)
                continue
            out.append(line)
    return out
