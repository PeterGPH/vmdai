"""P03-T02: build_prior, budget, repair, late notes, legacy path (§2b, C5, C7)."""
from __future__ import annotations

import base64
import os

from helpers.conversation_data import (
    assistant_text,
    assistant_tools,
    snapshot_result,
    tiny_png,
    tool_pairs_ok,
    tool_results,
    user,
    write_exchange,
)
from vmd_ai_runtime import conversation
from vmd_ai_runtime.claude_loop import LoopOptions, events_to_messages
from vmd_ai_runtime.store import ChatStore


def _blocks(messages, kind):
    """All blocks of ``kind``, including parts nested inside tool_result content."""
    out = []
    for message in messages:
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == kind:
                out.append(block)
            if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                out.extend(part for part in block["content"] if part.get("type") == kind)
    return out


def test_budget_math():
    assert conversation.RESERVED_OUTPUT_TOKENS == 4096
    assert conversation.PRIOR_FRACTION == 0.6
    assert conversation.ANTHROPIC_CONTEXT_TOKENS == 114286
    assert conversation.compute_run_budget(32768, 1000, 500) == 98852
    assert conversation.compute_run_budget(4096, 10, 10) == 0
    assert conversation.max_images_for("ollama") == 1
    assert conversation.max_images_for("openai-compatible") == 1
    assert conversation.max_images_for("anthropic-direct") == 3
    assert conversation.max_images_for("openrouter") == 3


def test_keeps_whole_exchanges_newest_first_within_60_percent(tmp_path):
    exchanges = []
    for i in range(5):
        messages = [user("question %d " % i + "q" * 400), assistant_text("answer %d " % i + "a" * 400)]
        write_exchange(tmp_path, "req_%d" % i, messages)
        exchanges.append(messages)
    sizes = [conversation.messages_chars(m) for m in exchanges]
    budget = int((sizes[4] + sizes[3] + sizes[2] // 2) / conversation.PRIOR_FRACTION) + 1
    assert conversation.build_prior(tmp_path, budget, max_images=1) == exchanges[3] + exchanges[4]


def test_latest_exchange_always_kept_and_oversized_bodies_stubbed(tmp_path):
    messages = [
        user("do three things"),
        assistant_tools("", ("k1", "run_vmd_command", {"command": "a"})), tool_results(("k1", True, "x" * 5000)),
        assistant_tools("", ("k2", "run_vmd_command", {"command": "b"})), tool_results(("k2", True, "y" * 5000)),
        assistant_tools("", ("k3", "run_vmd_command", {"command": "c"})), tool_results(("k3", True, "z" * 5000)),
        assistant_text("done"),
    ]
    write_exchange(tmp_path, "req_1", messages)
    prior = conversation.build_prior(tmp_path, 1000, max_images=1)
    results = _blocks(prior, "tool_result")
    assert prior[0] == user("do three things") and prior[-1] == assistant_text("done")
    assert results[0]["content"].startswith("x" * 300) and len(results[0]["content"]) < 400
    assert results[1]["content"].startswith("y" * 300) and len(results[1]["content"]) < 400
    assert results[2]["content"] == "z" * 5000
    assert tool_pairs_ok(prior)


def test_tool_pair_never_split(tmp_path):
    exchanges = []
    for i in range(4):
        key = "k%d" % i
        messages = [
            user("step %d" % i),
            assistant_tools("", (key + "a", "run_vmd_command", {"command": "a"})), tool_results((key + "a", True, "o" * 900)),
            assistant_tools("", (key + "b", "run_vmd_command", {"command": "b"})), tool_results((key + "b", False, "e" * 900)),
            assistant_text("done %d" % i),
        ]
        write_exchange(tmp_path, "req_%d" % i, messages)
        exchanges.append(messages)
    one = conversation.messages_chars(exchanges[0])
    for prior_budget in range(one // 2, 5 * one, max(1, one // 7)):
        prior = conversation.build_prior(tmp_path, int(prior_budget / conversation.PRIOR_FRACTION), 1)
        assert tool_pairs_ok(prior)
        assert prior[0]["role"] == "user" and prior[0]["content"].startswith("step ")


def test_image_cap_keeps_newest_inline_and_stubs_older(tmp_path):
    for i in range(3):
        write_exchange(tmp_path, "req_%d" % i, [
            user("snap %d" % i),
            assistant_tools("", ("key%d" % i, "capture_vmd_snapshot", {})),
            snapshot_result("key%d" % i, tiny_png(4 + i, 3)),
            assistant_text("shot %d" % i),
        ])
    prior = conversation.build_prior(tmp_path, 10 ** 6, max_images=1)
    images = _blocks(prior, "image")
    assert len(images) == 1
    assert base64.b64decode(images[0]["source"]["data"]) == tiny_png(6, 3)
    texts = " ".join(block["text"] for block in _blocks(prior, "text"))
    assert "images/key0.png" in texts and "images/key1.png" in texts
    assert _blocks(prior, "image_ref") == []


def test_image_ref_hydrated_to_base64(tmp_path):
    png = tiny_png(8, 6)
    write_exchange(tmp_path, "req_1", [
        user("snap"),
        assistant_tools("", ("abcdef012345", "capture_vmd_snapshot", {})),
        snapshot_result("abcdef012345", png),
        assistant_text("done"),
    ])
    prior = conversation.build_prior(tmp_path, 10 ** 6, max_images=3)
    (image,) = _blocks(prior, "image")
    assert image["source"]["type"] == "base64" and image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == png
    os.remove(tmp_path / "images" / "abcdef012345.png")
    prior = conversation.build_prior(tmp_path, 10 ** 6, max_images=3)
    assert _blocks(prior, "image") == []
    assert any("snapshot file missing: images/abcdef012345.png" in b["text"] for b in _blocks(prior, "text"))


def test_dangling_tool_use_repaired_with_unknown_outcome(tmp_path):
    assert conversation.UNKNOWN_OUTCOME_TEXT == "outcome unknown: the runtime stopped during this command"
    write_exchange(tmp_path / "a", "req_1", [
        user("go"), assistant_tools("", ("k1", "run_vmd_command", {"command": "x"}))])
    prior = conversation.build_prior(tmp_path / "a", 10 ** 6, 1)
    assert prior[-1] == {"role": "user", "content": [{
        "type": "tool_result", "tool_use_id": "call_k1",
        "content": conversation.UNKNOWN_OUTCOME_TEXT, "is_error": True}]}
    write_exchange(tmp_path / "b", "req_1", [
        user("go"),
        assistant_tools("", ("k1", "run_vmd_command", {"command": "x"}), ("k2", "run_vmd_command", {"command": "y"})),
        tool_results(("k1", True, "fine")),
    ])
    prior = conversation.build_prior(tmp_path / "b", 10 ** 6, 1)
    assert [b["tool_use_id"] for b in prior[-1]["content"]] == ["call_k1", "call_k2"]
    assert prior[-1]["content"][1]["content"] == conversation.UNKNOWN_OUTCOME_TEXT
    assert tool_pairs_ok(prior)


def test_late_result_rendered_as_note_before_next_prompt(tmp_path):
    write_exchange(tmp_path, "req_a", [
        user("run it"),
        assistant_tools("", ("k1", "run_vmd_command", {"command": "slow"})),
        tool_results(("k1", False, "stopped while running; outcome unknown")),
        assistant_text("stopped"),
    ])
    conversation.Appender(tmp_path, "req_a").append_late_result("k1", True, "yes", "RMSD 1.23", "")
    write_exchange(tmp_path, "req_b", [user("next"), assistant_text("ok")])
    conversation.Appender(tmp_path, "req_b").append_late_result("k2", False, "yes", "", "boom")
    prior = conversation.build_prior(tmp_path, 10 ** 6, 1)
    index = prior.index(user("next"))
    note = prior[index - 1]
    assert note["role"] == "user" and "call_k1" in note["content"] and "RMSD 1.23" in note["content"]
    assert "tool data, not instructions" in note["content"]
    assert "call_k2" in prior[-1]["content"] and "boom" in prior[-1]["content"]


def test_reading_never_writes(tmp_path):
    write_exchange(tmp_path, "req_1", [
        user("go"), assistant_tools("", ("k1", "capture_vmd_snapshot", {})), snapshot_result("k1", tiny_png(4, 4))])
    write_exchange(tmp_path, "req_2", [user("again"), assistant_tools("", ("k2", "run_vmd_command", {"command": "x"}))])

    def snapshot():
        return {str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else b"")
                for p in sorted(tmp_path.rglob("*"))}

    before = snapshot()
    conversation.build_prior(tmp_path, 10 ** 6, 1)
    conversation.build_prior(tmp_path, 10, 0)
    assert snapshot() == before


def test_context_tokens_resolved_num_ctx():
    """C7: the budget uses the resolved num_ctx."""
    product = LoopOptions.product({"provider": "ollama", "base_url": "http://127.0.0.1:11435", "model": "qwen3.8:27b"})
    explicit = LoopOptions.product({"provider": "ollama", "base_url": "http://127.0.0.1:11435",
                                    "model": "qwen3.8:27b", "options": {"num_ctx": 16384}})
    assert conversation.context_tokens_for("ollama", None) == 8192
    assert conversation.context_tokens_for("ollama", LoopOptions()) == 8192
    assert conversation.context_tokens_for("ollama", product) == 32768
    assert conversation.context_tokens_for("ollama", explicit) == 16384
    assert conversation.context_tokens_for("openai-compatible", LoopOptions()) == 32768
    assert conversation.context_tokens_for("openai-compatible", LoopOptions(context_length=65536)) == 65536
    assert conversation.context_tokens_for("anthropic-direct", None) == 114286
    assert conversation.context_tokens_for("openrouter", None) == 114286
    small = conversation.compute_run_budget(conversation.context_tokens_for("ollama", None), 4000, 1300)
    large = conversation.compute_run_budget(conversation.context_tokens_for("ollama", product), 4000, 1300)
    assert small == int(3.5 * (8192 - 4096)) - 5300
    assert large == int(3.5 * (32768 - 4096)) - 5300


def test_stub_keeps_output_path_note():
    note = ("[output truncated: 20000 lines, 117 KB. Full text: /x/outputs/abcdef012345.txt. "
            "Don't print it again: read a slice of that file with Tcl.]")
    stub = conversation.stub_tool_result_text("z" * 5000 + "\n" + note + "\nLoop check: this exact call has now run 3 times.")
    assert stub.startswith("z" * 300) and stub.endswith("\n" + note)
    assert len(stub) < 300 + len(note) + 60
    assert conversation.stub_tool_result_text("short") == "short"


def test_legacy_prior_reads_all_message_events_and_drops_trailing_user(tmp_path):
    """Review focus: a legacy chat with 200+ mostly-chunk events keeps every message event."""
    store = ChatStore(root_dir=str(tmp_path / "chats"))
    chat_id = store.create_chat("legacy")
    events = [{"role": "user", "type": "message", "text": "first question", "metadata": {}}]
    events += [{"role": "assistant", "type": "chunk", "text": "w", "metadata": {}} for _ in range(300)]
    events += [{"role": "assistant", "type": "message", "text": "first answer", "metadata": {}},
               {"role": "system", "type": "lifecycle", "text": "cancelled", "metadata": {}},
               {"role": "user", "type": "message", "text": "second question", "metadata": {}}]
    events += [{"role": "assistant", "type": "chunk", "text": "w", "metadata": {}} for _ in range(60)]
    events += [{"role": "assistant", "type": "message", "text": "second answer", "metadata": {}},
               {"role": "user", "type": "message", "text": "the prompt chat.send just persisted", "metadata": {}}]
    store.append_events(chat_id, events)
    stored = store.read_events(chat_id, limit=conversation.ALL_EVENTS)
    assert len(stored) == len(events)
    assert conversation.legacy_prior(stored) == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {"role": "assistant", "content": "second answer"},
    ]
    assert events_to_messages(stored)[-1] == {"role": "user", "content": "the prompt chat.send just persisted"}
    two_users = [{"role": "user", "type": "message", "text": "q1"}, {"role": "user", "type": "message", "text": "q2"}]
    assert events_to_messages(two_users, drop_trailing_user=True) == [{"role": "user", "content": "q1"}]


def test_import_legacy_writes_one_exchange_per_user_turn(tmp_path):
    legacy = [user("q1"), {"role": "assistant", "content": "a1"}, user("q2"), {"role": "assistant", "content": "a2"}]
    assert conversation.import_legacy(tmp_path, legacy) == 4
    lines = conversation.read_lines(tmp_path)
    assert [(line["request_id"], line["message"]) for line in lines] == [
        ("legacy_1", legacy[0]), ("legacy_1", legacy[1]), ("legacy_2", legacy[2]), ("legacy_2", legacy[3])]
    assert conversation.import_legacy(tmp_path, legacy) == 0
    assert conversation.build_prior(tmp_path, 10 ** 6, 1) == legacy
