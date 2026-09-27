"""P03-T01: conversation.Appender and the messages.jsonl format (§2b, C5)."""
from __future__ import annotations

import json
import logging

from helpers.conversation_data import (
    assistant_tools,
    snapshot_result,
    tiny_png,
    tool_results,
    user,
)
from vmd_ai_runtime import conversation


def _lines(chat_dir):
    text = conversation.messages_path(chat_dir).read_text(encoding="ascii")
    return [json.loads(line) for line in text.splitlines()]


def test_one_line_per_append(tmp_path):
    appender = conversation.Appender(tmp_path, "req_1", clock=lambda: 1000.0)
    messages = [
        user("load 1hck"),
        assistant_tools("Loading.", ("abcdef012345", "run_vmd_command", {"command": "mol new 1hck.pdb"})),
        tool_results(("abcdef012345", True, "Info) Loaded 1hck")),
    ]
    for message in messages:
        appender.append(message)
    lines = _lines(tmp_path)
    assert len(lines) == 3
    for line, message in zip(lines, messages):
        assert line == {"v": 1, "kind": "message", "request_id": "req_1", "ts": 1000.0, "message": message}
    assert conversation.messages_path(tmp_path) == tmp_path / "messages.jsonl"
    assert conversation.CHARS_PER_TOKEN == 3.5 and conversation.STORE_OUTPUT_CAP == 6000


def test_image_block_becomes_image_ref_and_file(tmp_path):
    png = tiny_png(8, 6)
    conversation.Appender(tmp_path, "req_1").append(snapshot_result("abcdef012345", png))
    stored = _lines(tmp_path)[0]["message"]["content"][0]
    assert stored["type"] == "tool_result" and stored["tool_use_id"] == "call_abcdef012345"
    assert stored["content"][0] == {"type": "text", "text": "Snapshot captured."}
    assert stored["content"][1] == {"type": "image_ref", "path": "images/abcdef012345.png",
                                    "media_type": "image/png", "width": 8, "height": 6}
    assert (tmp_path / "images" / "abcdef012345.png").read_bytes() == png
    assert '"base64"' not in conversation.messages_path(tmp_path).read_text(encoding="ascii")


def test_existing_image_file_not_rewritten(tmp_path):
    (tmp_path / "images").mkdir()
    existing = tmp_path / "images" / "abcdef012345.png"
    existing.write_bytes(b"written by the bridge")
    conversation.Appender(tmp_path, "req_1").append(snapshot_result("abcdef012345", tiny_png(4, 4)))
    assert existing.read_bytes() == b"written by the bridge"
    assert _lines(tmp_path)[0]["message"]["content"][0]["content"][1]["path"] == "images/abcdef012345.png"


def test_late_result_line(tmp_path):
    appender = conversation.Appender(tmp_path, "req_9", clock=lambda: 2000.5)
    appender.append_late_result("abcdef012345", True, "yes", "RMSD 1.23", "")
    assert _lines(tmp_path) == [{
        "v": 1, "kind": "late_result", "request_id": "req_9", "ts": 2000.5,
        "call_key": "abcdef012345", "ok": True, "executed": "yes", "output": "RMSD 1.23", "error": "",
    }]


def test_store_cap_output_section_only(tmp_path):
    note = ("[output truncated: 20000 lines, 117 KB. Full text: /tmp/chats/chat_0/outputs/abcdef012345.txt. "
            "Don't print it again: compute what you need (measure, a narrower selection), "
            "or read a slice of that file with Tcl.]")
    nudge = "Loop check: this exact call has now run 3 times with the same result."
    body = "".join("%05d 1.000 2.000 3.000\n" % i for i in range(20000))
    text = body + note + "\n" + nudge
    capped = conversation.cap_output_section(text)
    assert capped.endswith("\n" + note + "\n" + nudge)
    output_part, tail = conversation.split_output_section(capped)
    assert tail == "\n" + note + "\n" + nudge
    assert len(output_part) <= conversation.STORE_OUTPUT_CAP + 50
    assert output_part.startswith("00000 1.000") and output_part.endswith("19999 1.000 2.000 3.000")
    assert conversation.cap_output_section("short\n" + note) == "short\n" + note
    # C3's failure lines sit in front of the output and are not counted or cut.
    failure = ("Failed at statement 2 of 2: `puts $big`\nError: boom\n"
               "Statement 1 was applied and is still in effect; do not re-run it.\n"
               "Output before the error:\n")
    assert conversation.cap_output_section(failure + "o" * 5900) == failure + "o" * 5900
    capped_failure = conversation.cap_output_section(failure + "o" * 9000)
    assert capped_failure.startswith(failure) and capped_failure.endswith("o" * 3000)
    assert len(capped_failure) <= len(failure) + conversation.STORE_OUTPUT_CAP + 50
    conversation.Appender(tmp_path, "req_1").append(tool_results(("abcdef012345", True, text)))
    assert _lines(tmp_path)[0]["message"]["content"][0]["content"] == capped


def test_warns_at_2mb(tmp_path, caplog):
    appender = conversation.Appender(tmp_path, "req_1")
    with caplog.at_level(logging.WARNING, logger="vmdai.conversation"):
        appender.append(user("x" * (conversation.STORE_WARN_BYTES + 10)))
        appender.append(user("again"))
    warnings = [r for r in caplog.records if "over 2 MB" in r.getMessage()]
    assert len(warnings) == 1


def test_read_lines_skips_unknown_kind_and_undecodable(tmp_path, caplog):
    """Review focus: a crash mid-write leaves a truncated last line; it is
    skipped and the earlier lines survive."""
    appender = conversation.Appender(tmp_path, "req_1", clock=lambda: 1.0)
    appender.append(user("first"))
    appender.append_late_result("abcdef012345", False, "unknown", "", "stopped")
    with open(conversation.messages_path(tmp_path), "ab") as handle:
        handle.write(b'{"v":1,"kind":"pending_approval","request_id":"req_1"}\n')
        handle.write(b"this is not json\n")
        handle.write(b"\xff\xfe\n")
        handle.write(b'{"v":1,"kind":"message","request_id":"req_2","ts":2.0,"mess')
    with caplog.at_level(logging.WARNING, logger="vmdai.conversation"):
        lines = conversation.read_lines(tmp_path)
    assert [line["kind"] for line in lines] == ["message", "late_result"]
    assert lines[0]["message"] == user("first")
    assert len([r for r in caplog.records if "skipped" in r.getMessage()]) == 4
    assert conversation.read_lines(tmp_path / "missing") == []
