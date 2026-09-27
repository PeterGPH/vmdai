#!/usr/bin/env python3
"""Record provider cassettes for tests/cassettes/ (round-1 spec C9).

Recording (needs a live Ollama, e.g. through the SSH tunnel):

    python scripts/record_cassettes.py --base-url http://127.0.0.1:11435 \
        --model qwen3.8:27b --out tests/cassettes/ollama

--base-url and --model default to the live gates VMD_AI_LIVE_OLLAMA and
VMD_AI_LIVE_MODEL. Each scenario drives the real product code
(_stream_ollama with LoopOptions.product(), and provider_catalog's probes)
through a wrapper around urllib.request.urlopen, so a cassette holds exactly
the requests the product makes, in order. The server URL is rewritten to
http://ollama.test, request bodies are kept only as SHA-256 fingerprints and
request headers (Authorization, x-api-key) are never written.

Synthesizing (no server needed):

    python scripts/record_cassettes.py --synthesize

writes the four cassettes no credit-free server can produce, with
meta.synthetic = true. Real-server cassettes are never synthesized.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime
import email.message
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "runtime") not in sys.path:
    sys.path.insert(0, str(REPO / "runtime"))

from vmd_ai_runtime import claude_loop, image_scale, provider_catalog  # noqa: E402
from vmd_ai_runtime.claude_loop import (  # noqa: E402
    ClaudeLoopError,
    LoopOptions,
    _stream_ollama,
    _vmd_tools,
)

REWRITTEN_BASE = "http://ollama.test"
CASSETTE_ROOT = REPO / "tests" / "cassettes"
SNAPSHOT = REPO / "docs" / "design" / "round1" / "assets" / "snap_1hck.png"
MISSING_MODEL = "vmdai-no-such-model:latest"
SYSTEM = "You are ChatVMD, an assistant inside VMD. Use the tools when the user asks for an action."
TRUNCATE_BUDGETS = (40, 64, 96, 128)
PLAIN_PROMPT = [{"role": "user", "content": (
    "In one short sentence, what does the VMD command `mol new` do? "
    "Answer in prose and do not call any tool.")}]
LOAD_PROMPT = [{"role": "user", "content": "Load the local file 1hck.pdb into VMD."}]
TWO_STEP_PROMPT = [{"role": "user", "content": (
    "Load 1hck.pdb into VMD, then in a second, separate tool call set the "
    "background colour to white.")}]


def _path_of(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return parts.path + ("?" + parts.query if parts.query else "")


class _Replay:
    """The recorded response, handed back to the product code unchanged."""

    def __init__(self, url: str, status: int, content_type: str, body: bytes) -> None:
        self.url = url
        self.status = status
        self.code = status
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type
        self._buf = io.BytesIO(body)

    def read(self, amt: Optional[int] = None) -> bytes:
        return self._buf.read() if amt is None or amt < 0 else self._buf.read(amt)

    def readline(self, limit: int = -1) -> bytes:
        return self._buf.readline(limit)

    def __iter__(self):
        return iter(self._buf.readline, b"")

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url

    def info(self) -> email.message.Message:
        return self.headers

    def close(self) -> None:
        pass

    def __enter__(self) -> "_Replay":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class Recorder:
    """Wraps a real urlopen; keeps method, path, body hash, status, content
    type and response body lines. Request headers are never kept."""

    def __init__(self, inner: Callable[..., Any], *, base_url: str,
                 mutate_body: Optional[Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> None:
        self.inner = inner
        self.base_url = base_url.rstrip("/")
        self.netloc = urllib.parse.urlsplit(self.base_url).netloc
        self.mutate_body = mutate_body
        self.exchanges: List[Dict[str, Any]] = []

    def urlopen(self, req: Any, timeout: Optional[float] = None, **kwargs: Any) -> _Replay:
        if isinstance(req, str):
            req = urllib.request.Request(req)
        if self.mutate_body is not None and req.data:
            changed = self.mutate_body(_path_of(req.full_url), json.loads(req.data))
            if changed is not None:
                req = urllib.request.Request(
                    req.full_url,
                    data=json.dumps(changed).encode("utf-8"),
                    headers=dict(req.header_items()),
                    method=req.get_method(),
                )
        method = req.get_method()
        path = _path_of(req.full_url)
        digest = hashlib.sha256(req.data or b"").hexdigest()
        try:
            resp = self.inner(req, timeout=timeout, **kwargs)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            ctype = exc.headers.get("Content-Type", "") if exc.headers is not None else ""
            self._keep(method, path, digest, exc.code, ctype, body)
            raise urllib.error.HTTPError(req.full_url, exc.code, exc.reason, exc.headers, io.BytesIO(body))
        with resp:
            body = resp.read()
            status = int(getattr(resp, "status", 0) or resp.getcode())
            ctype = resp.headers.get("Content-Type", "")
        self._keep(method, path, digest, status, ctype, body)
        return _Replay(req.full_url, status, ctype, body)

    def _keep(self, method: str, path: str, digest: str, status: int, ctype: str, body: bytes) -> None:
        text = body.decode("utf-8", errors="replace")
        text = text.replace(self.base_url, REWRITTEN_BASE).replace(self.netloc, "ollama.test")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        self.exchanges.append({
            "method": method,
            "path": path,
            "request_sha256": digest,
            "status": int(status),
            "content_type": ctype,
            "body_lines": lines,
        })


# ---------------------------------------------------------------- recording

def _product(base_url: str, model: str, **overrides: Any) -> LoopOptions:
    opts = LoopOptions.product({"provider": "ollama", "base_url": base_url, "model": model, "options": {}})
    # A cold 27B load over the tunnel can take longer than the product's 120 s.
    overrides.setdefault("first_byte_timeout_s", 600.0)
    return dataclasses.replace(opts, **overrides)


def _stream(base_url: str, model: str, messages: List[Dict[str, Any]], opts: LoopOptions) -> Tuple[str, List[Dict[str, Any]]]:
    return _stream_ollama(
        messages=messages, model=model, system_prompt=SYSTEM, base_url=base_url,
        timeout=600, on_text=lambda text: None, should_cancel=lambda: False,
        tools=_vmd_tools(include_search_docs=False, include_wiki=False),
        on_meta=lambda item: None, opts=opts,
    )


def _record(base_url: str, action: Callable[[], Any],
            mutate_body: Optional[Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    provider_catalog.clear_caches()
    claude_loop._NO_THINK.clear()
    recorder = Recorder(urllib.request.urlopen, base_url=base_url, mutate_body=mutate_body)
    with mock.patch("urllib.request.urlopen", new=recorder.urlopen):
        action()
    return recorder.exchanges


def _chat_lines(exchanges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ex in exchanges:
        if ex["path"] == "/api/chat" and ex["status"] == 200:
            out.extend(json.loads(line) for line in ex["body_lines"] if line.strip())
    return out


def _has(lines: List[Dict[str, Any]], key: str) -> bool:
    return any((line.get("message") or {}).get(key) for line in lines)


def _done_reason(lines: List[Dict[str, Any]]) -> Optional[str]:
    return next((line.get("done_reason") for line in lines if line.get("done")), None)


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit("record_cassettes: " + message)


def _vision_messages() -> List[Dict[str, Any]]:
    png, _w, _h = image_scale.downscale_png(SNAPSHOT.read_bytes(), 1024)
    b64 = base64.b64encode(png).decode("ascii")
    return [
        {"role": "user", "content": "Take a snapshot, then tell me what colour the arrow-shaped beta strands are."},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "otc_1", "name": "capture_vmd_snapshot",
                                           "input": {"purpose": "look at the scene"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "otc_1", "is_error": False, "content": [
            {"type": "text", "text": "Snapshot captured."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
        ]}]},
    ]


def scenario_plain_answer(base: str, model: str) -> Tuple[List[Dict[str, Any]], str]:
    ex = _record(base, lambda: _stream(base, model, PLAIN_PROMPT, _product(base, model, think=False)))
    lines = _chat_lines(ex)
    _require(_done_reason(lines) == "stop" and not _has(lines, "tool_calls"),
             "plain_answer: expected a finished answer without tool calls")
    return ex, model


def scenario_tool_call(base: str, model: str) -> Tuple[List[Dict[str, Any]], str]:
    ex = _record(base, lambda: _stream(base, model, LOAD_PROMPT, _product(base, model, think=False)))
    _require(_has(_chat_lines(ex), "tool_calls"), "tool_call: the model answered without a tool call")
    return ex, model


def scenario_thinking_tool_call(base: str, model: str) -> Tuple[List[Dict[str, Any]], str]:
    ex = _record(base, lambda: _stream(base, model, LOAD_PROMPT, _product(base, model, think=True)))
    lines = _chat_lines(ex)
    _require(_has(lines, "thinking") and _has(lines, "tool_calls"),
             "thinking_tool_call: expected message.thinking and a tool call")
    return ex, model


def scenario_vision_turn(base: str, model: str) -> Tuple[List[Dict[str, Any]], str]:
    messages = _vision_messages()
    ex = _record(base, lambda: _stream(base, model, messages, _product(base, model, think=False, supports_vision=True)))
    lines = _chat_lines(ex)
    text = "".join((line.get("message") or {}).get("content") or "" for line in lines)
    _require(_done_reason(lines) == "stop" and bool(text.strip()), "vision_turn: expected a text answer")
    return ex, model


def scenario_truncated_tool_call(base: str, model: str) -> Tuple[List[Dict[str, Any]], str]:
    last: Optional[List[Dict[str, Any]]] = None
    for budget in TRUNCATE_BUDGETS:
        def cut(path: str, body: Dict[str, Any], budget: int = budget) -> Optional[Dict[str, Any]]:
            if path != "/api/chat":
                return None
            body.setdefault("options", {})["num_predict"] = budget
            return body
        ex = _record(base, lambda: _stream(base, model, TWO_STEP_PROMPT, _product(base, model, think=False)),
                     mutate_body=cut)
        lines = _chat_lines(ex)
        if _done_reason(lines) == "length":
            last = ex
            if _has(lines, "tool_calls"):
                return ex, model
    _require(last is not None, "truncated_tool_call: no num_predict budget ended with done_reason 'length'")
    print("record_cassettes: truncated_tool_call ends with done_reason 'length' but holds no tool_calls; "
          "the parser test then pins the no-call branch")
    return last, model


def scenario_model_not_found(base: str, model: str) -> Tuple[List[Dict[str, Any]], str]:
    def act() -> None:
        try:
            _stream(base, MISSING_MODEL, LOAD_PROMPT, _product(base, MISSING_MODEL, think=False))
        except ClaudeLoopError:
            return
        raise SystemExit("record_cassettes: model_not_found: the server accepted an unknown model")
    ex = _record(base, act)
    _require(bool(ex) and ex[-1]["path"] == "/api/chat" and ex[-1]["status"] == 404,
             "model_not_found: expected /api/chat to answer 404")
    return ex, MISSING_MODEL


def scenario_version_ps(base: str, model: str) -> Tuple[List[Dict[str, Any]], str]:
    ex = _record(base, lambda: (provider_catalog.ollama_version(base, timeout=2.0),
                                provider_catalog.ollama_ps(base, timeout=2.0)))
    _require([e["path"] for e in ex] == ["/api/version", "/api/ps"],
             "version_ps: expected exactly /api/version then /api/ps")
    return ex, model


SCENARIOS: Dict[str, Callable[[str, str], Tuple[List[Dict[str, Any]], str]]] = {
    "plain_answer": scenario_plain_answer,
    "tool_call": scenario_tool_call,
    "thinking_tool_call": scenario_thinking_tool_call,
    "vision_turn": scenario_vision_turn,
    "truncated_tool_call": scenario_truncated_tool_call,
    "model_not_found": scenario_model_not_found,
    "version_ps": scenario_version_ps,
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _server_facts(base: str, model: str) -> Tuple[str, Optional[str]]:
    provider_catalog.clear_caches()
    version = provider_catalog.ollama_version(base, timeout=2.0)
    digest: Optional[str] = None
    for entry in provider_catalog.ollama_ps(base, timeout=2.0):
        if model in (entry.get("name"), entry.get("model")):
            digest = entry.get("digest") or None
    if digest is None:
        provider_catalog.list_models("ollama", base)
        digest = provider_catalog.cached_tag_digest(base, model)
    return version, digest


def write_cassette(path: Path, meta: Dict[str, Any], exchanges: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"meta": meta, "exchanges": exchanges}, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def record_all(base: str, model: str, out: Path, only: List[str]) -> None:
    version, digest = _server_facts(base, model)
    names = only or list(SCENARIOS)
    for name in names:
        exchanges, used_model = SCENARIOS[name](base, model)
        meta = {
            "recorded_at": _now(), "provider": "ollama", "server_version": version,
            "model": used_model, "model_digest": digest if used_model == model else None,
            "synthetic": False,
        }
        write_cassette(out / f"{name}.json", meta, exchanges)
        print(f"recorded {out / (name + '.json')} ({len(exchanges)} exchanges)")


# ------------------------------------------------------------- synthesizing

SYN_RECORDED_AT = "2026-09-24T00:00:00Z"
SYN_DIGEST = "5f7b1a2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff"
JSON_CT = "application/json; charset=utf-8"
NDJSON_CT = "application/x-ndjson"
SSE_CT = "text/event-stream"
FENCE = "`" * 3  # built at run time so this file can sit inside a Markdown code fence
PROSE_WITH_TCL = (
    "To make the background white you would run:\n"
    + FENCE + "tcl\ncolor Display Background white\n" + FENCE + "\n"
    + "Say the word and I will do it."
)
MIXED_TOOL_TEXT = (
    "I will load it.\n"
    + FENCE + "tcl\nmol delete all\n" + FENCE + "\n"
    + "{\"name\": \"shell_exec\", \"arguments\": {\"cmd\": \"ls\"}}\n"
    + FENCE + "json\n{\"name\": \"run_vmd_command\", \"arguments\": {\"command\": \"mol new 1hck.pdb\"}}\n"
    + FENCE
)


def _line(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _ex(method: str, path: str, status: int, content_type: str, lines: List[str]) -> Dict[str, Any]:
    return {"method": method, "path": path, "request_sha256": "", "status": status,
            "content_type": content_type, "body_lines": lines}


def _syn_meta(provider: str, model: str, server_version: str, digest: Optional[str]) -> Dict[str, Any]:
    return {"recorded_at": SYN_RECORDED_AT, "provider": provider, "server_version": server_version,
            "model": model, "model_digest": digest, "synthetic": True}


def _version() -> Dict[str, Any]:
    return _ex("GET", "/api/version", 200, JSON_CT, [_line({"version": "0.12.0"})])


def _ps(model: str) -> Dict[str, Any]:
    entry = {"name": model, "model": model, "size": 6654289920, "digest": SYN_DIGEST,
             "expires_at": "2026-09-24T01:00:00Z", "size_vram": 6654289920}
    return _ex("GET", "/api/ps", 200, JSON_CT, [_line({"models": [entry]})])


def _chat(model: str, contents: List[str], *, prompt_eval: int = 310, evals: int = 12) -> Dict[str, Any]:
    lines = [_line({"model": model, "created_at": "2026-09-24T00:00:01Z",
                    "message": {"role": "assistant", "content": text}, "done": False}) for text in contents]
    lines.append(_line({"model": model, "created_at": "2026-09-24T00:00:02Z",
                        "message": {"role": "assistant", "content": ""}, "done": True,
                        "done_reason": "stop", "prompt_eval_count": prompt_eval, "eval_count": evals}))
    return _ex("POST", "/api/chat", 200, NDJSON_CT, lines)


def _sse_lines(events: List[Any]) -> List[str]:
    lines: List[str] = []
    for event in events:
        if isinstance(event, tuple):
            lines.append("event: " + event[0])
            payload = event[1]
        else:
            payload = event
        lines.append("data: " + (payload if isinstance(payload, str) else _line(payload)))
        lines.append("")
    return lines


def _openai_chunk(delta: Dict[str, Any], finish: Optional[str] = None) -> Dict[str, Any]:
    return {"id": "chatcmpl-syn1", "object": "chat.completion.chunk", "model": "qwen3-32b",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def _anthropic_start(input_tokens: int, cache_read: int) -> Tuple[str, Dict[str, Any]]:
    return ("message_start", {"type": "message_start", "message": {
        "id": "msg_syn1", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5",
        "content": [], "stop_reason": None,
        "usage": {"input_tokens": input_tokens, "cache_read_input_tokens": cache_read,
                  "cache_creation_input_tokens": 0, "output_tokens": 1}}})


def synthetic_cassettes() -> Dict[Tuple[str, str], Dict[str, Any]]:
    think_model = "llama3.1:8b"
    rescue_model = "qwen3.8:27b"
    return {
        ("ollama", "think_unsupported"): {
            "meta": _syn_meta("ollama", think_model, "0.12.0", SYN_DIGEST),
            "exchanges": [
                _version(),
                _ps(think_model),
                _ex("POST", "/api/chat", 400, JSON_CT,
                    [_line({"error": "\"%s\" does not support thinking" % think_model})]),
                # The retry runs the preflight again: /api/version is cached,
                # /api/ps is not (spec 2f).
                _ps(think_model),
                _chat(think_model, ["VMD loads ", "molecules."]),
            ],
        },
        ("ollama", "rescue_json"): {
            "meta": _syn_meta("ollama", rescue_model, "0.12.0", SYN_DIGEST),
            "exchanges": [
                _version(),
                _ps(rescue_model),
                _chat(rescue_model, [PROSE_WITH_TCL]),
                _ps(rescue_model),
                _chat(rescue_model, [MIXED_TOOL_TEXT]),
            ],
        },
        ("openai-compatible", "reasoning_usage"): {
            "meta": _syn_meta("openai-compatible", "qwen3-32b", "vllm (synthetic)", None),
            "exchanges": [_ex("POST", "/v1/chat/completions", 200, SSE_CT, _sse_lines([
                _openai_chunk({"role": "assistant", "reasoning_content": "The user asks for "}),
                _openai_chunk({"reasoning_content": "the chain count."}),
                _openai_chunk({"content": "The structure has "}),
                _openai_chunk({"content": "one chain."}, finish="stop"),
                {"id": "chatcmpl-syn1", "object": "chat.completion.chunk", "model": "qwen3-32b",
                 "choices": [], "usage": {"prompt_tokens": 812, "completion_tokens": 24, "total_tokens": 836}},
                "[DONE]",
            ]))],
        },
        ("anthropic-direct", "usage_error"): {
            "meta": _syn_meta("anthropic-direct", "claude-sonnet-4-5", "", None),
            "exchanges": [
                _ex("POST", "/v1/messages", 200, SSE_CT, _sse_lines([
                    _anthropic_start(1024, 256),
                    ("content_block_start", {"type": "content_block_start", "index": 0,
                                             "content_block": {"type": "text", "text": ""}}),
                    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                             "delta": {"type": "text_delta", "text": "Done."}}),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    ("message_delta", {"type": "message_delta",
                                       "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                       "usage": {"output_tokens": 42}}),
                    ("message_stop", {"type": "message_stop"}),
                ])),
                _ex("POST", "/v1/messages", 200, SSE_CT, _sse_lines([
                    _anthropic_start(900, 0),
                    ("error", {"type": "error", "error": {"type": "api_error", "message": "Internal server error"}}),
                ])),
            ],
        },
    }


def synthesize(root: Path) -> None:
    for (provider, name), cassette in synthetic_cassettes().items():
        path = root / provider / f"{name}.json"
        write_cassette(path, cassette["meta"], cassette["exchanges"])
        print(f"synthesized {path}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=os.environ.get("VMD_AI_LIVE_OLLAMA", ""))
    parser.add_argument("--model", default=os.environ.get("VMD_AI_LIVE_MODEL", ""))
    parser.add_argument("--out", default=str(CASSETTE_ROOT / "ollama"))
    parser.add_argument("--only", action="append", default=[], choices=sorted(SCENARIOS))
    parser.add_argument("--synthesize", action="store_true",
                        help="write the synthetic cassettes under --cassette-root and exit")
    parser.add_argument("--cassette-root", default=str(CASSETTE_ROOT))
    args = parser.parse_args(argv)
    if args.synthesize:
        synthesize(Path(args.cassette_root))
        return 0
    if not args.base_url.startswith(("http://", "https://")) or not args.model:
        parser.error("pass --base-url http://host:port and --model (or set VMD_AI_LIVE_OLLAMA and VMD_AI_LIVE_MODEL)")
    record_all(args.base_url.rstrip("/"), args.model, Path(args.out), args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
