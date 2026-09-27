"""A scripted urllib.request.urlopen for loop tests (plan 05).

Routes by URL path: /api/version and /api/ps (Ollama preflight) and
/api/show answer from fixed JSON; the chat endpoints (/api/chat,
/v1/messages, /chat/completions) pop the next scripted body, or raise it
when it is an exception. Any other path fails the test.
"""
from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Union

CHAT_PATHS = ("/api/chat", "/v1/messages", "/chat/completions")


class FakeResponse(io.BytesIO):
    status = 200

    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers: Dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def getcode(self) -> int:
        return 200

    def getheader(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return default


class FakeHTTP:
    def __init__(
        self,
        chat: List[Union[bytes, BaseException]],
        *,
        ps: Optional[Dict[str, Any]] = None,
        version: str = "0.12.3",
        on_chat: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.chat = list(chat)
        self.ps = ps if ps is not None else {"models": []}
        self.version = version
        self.on_chat = on_chat
        self.bodies: List[Dict[str, Any]] = []
        self.urls: List[str] = []

    def __call__(self, req: Any, timeout: Optional[float] = None, *args: Any, **kwargs: Any) -> FakeResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.urls.append(url)
        path = urllib.parse.urlsplit(url).path
        if path.endswith("/api/version"):
            return FakeResponse(json.dumps({"version": self.version}).encode("utf-8"))
        if path.endswith("/api/ps"):
            return FakeResponse(json.dumps(self.ps).encode("utf-8"))
        if path.endswith("/api/show"):
            return FakeResponse(json.dumps({"capabilities": ["completion", "tools"],
                                            "model_info": {}}).encode("utf-8"))
        if path.endswith(CHAT_PATHS):
            data = getattr(req, "data", None) or b"{}"
            body = json.loads(data.decode("utf-8"))
            self.bodies.append(body)
            if self.on_chat is not None:
                self.on_chat(body)
            if not self.chat:
                raise AssertionError("unexpected extra chat request to " + url)
            item = self.chat.pop(0)
            if isinstance(item, BaseException):
                raise item
            return FakeResponse(item)
        raise AssertionError("unexpected request: " + url)


def _ndjson(events: List[Dict[str, Any]]) -> bytes:
    return "".join(json.dumps(e) + "\n" for e in events).encode("utf-8")


def _sse(events: List[Any]) -> bytes:
    out = []
    for event in events:
        if event == "[DONE]":
            out.append("data: [DONE]\n\n")
        else:
            out.append("data: " + json.dumps(event) + "\n\n")
    return "".join(out).encode("utf-8")


def ollama_tool_call(command: str, call_id: Optional[str] = None) -> bytes:
    return ollama_tool_calls(command)


def ollama_tool_calls(*commands: str) -> bytes:
    """One Ollama turn that calls run_vmd_command once per command."""
    return _ndjson([{
        "model": "m",
        "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_vmd_command", "arguments": {"command": command}}}
            for command in commands]},
        "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5,
    }])


def ollama_text(text: str) -> bytes:
    return _ndjson([{
        "model": "m", "message": {"role": "assistant", "content": text},
        "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5,
    }])


def anthropic_tool_call(command: str, call_id: str = "toolu_01") -> bytes:
    return _sse([
        {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": call_id, "name": "run_vmd_command", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": json.dumps({"command": command})}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ])


def anthropic_text(text: str) -> bytes:
    return _sse([
        {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    ])


def openai_tool_call(command: str, call_id: str = "call_1") -> bytes:
    return _sse([
        {"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
            {"index": 0, "id": call_id, "type": "function",
             "function": {"name": "run_vmd_command", "arguments": json.dumps({"command": command})}}]},
            "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])


def openai_text(text: str) -> bytes:
    return _sse([
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        "[DONE]",
    ])


def http_error(url: str, code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", email.message.Message(), io.BytesIO(body))
