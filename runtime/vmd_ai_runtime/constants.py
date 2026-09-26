from __future__ import annotations

EVENT_ROLES = (
    "user",
    "assistant",
    "system",
    "error",
    "tool_start",    # Python→Tcl: a VMD tool call is pending execution
    "tool_result",   # Tcl→Python: result of a VMD tool call (stored in history)
    "reasoning",
)

EVENT_TYPES = (
    "message",
    "chunk",
    "state",
    "lifecycle",
)

DEFAULT_SETTINGS = {
    "model": "anthropic/claude-sonnet-4.6",
    "mode": "work",
    "conversation_mode": "local_first",
    "reasoning_visible": True,
    "debug_mode": False,
}

CAPABILITIES = {
    "streaming": True,
    "tools": ["run_vmd_command", "capture_vmd_snapshot"],
    "agent_loop": True,     # Claude drives tool calls autonomously
    "history": True,
    "keys": ["openrouter", "anthropic"],
}

CONVERSATION_MODES = ("local_first", "hybrid_resume", "resume_only")

# Runtime RPC/auth protocol, reported in the READY line, /health and
# runtime.info (§2c). 2 = launch token + tool.ack. It is separate from the
# per-session event_protocol that session.start negotiates.
RUNTIME_PROTOCOL = 2
RUNTIME_VERSION = "0.3.0"
