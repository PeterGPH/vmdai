"""Generate the five v2 scenario event fixtures from the runtime (§6, C4).

Each scenario drives RuntimeApp in process: a token session that negotiated
event_protocol 2, a scripted model (helpers.events_v2.MetaScriptedLoop, which
streams reasoning, usage and status through the loop's own on_meta path) and
a product-shaped bridge. What the session polls is normalised and written one
§2c envelope per line to tests/fixtures/events/<name>.jsonl.
tests/test_event_fixtures.py regenerates every fixture and compares it with
the file; CHATVMD_UPDATE_GOLDENS=1 rewrites the files.

Normalisation (stable across runs and machines):
  * ts          -> 1790208000.0 + 0.5 s per line
  * duration_ms -> 500 ms per line from the start line to the end line
                   (tool.started -> tool.finished by call_key,
                    request.started -> request.finished by request_id,
                    first reasoning chunk -> reasoning/message by turn)
  * req_/chat_/sess_ ids and call keys -> numbered in order of appearance
                   (req_000000000001, chat_000000000001, 000000000001)
  * repository root -> @REPO@, the scenario's temp dir -> @WORK@
11_dead_runtime ends with plugin-local events (seq 0) the M2 plugin emits
itself after the runtime dies: local.connection, local.send_failed,
local.request_ended.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Sequence

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (MetaScriptedLoop, ProductBridge, ScriptTurn, poll_all, product_result,
                               run_cmd, start_v2, tool_block)

REPO = Path(__file__).resolve().parents[2]
EVENTS_DIR = REPO / "tests" / "fixtures" / "events"
SCENARIOS = ("03_conversation", "11_dead_runtime", "reasoning_answer", "turn_retry", "loop_guard")
BASE_TS = 1790208000.0          # 2026-09-24T00:00:00Z
STEP_S = 0.5                    # normalised seconds between consecutive lines
SNAPSHOT_PNG = REPO / "docs" / "design" / "round1" / "assets" / "snap_1hck.png"   # 1280 x 1547

CONVERSATION_PROMPTS = ("load 1hck and show it as a cartoon", "what is its radius of gyration?")
CONVERSATION_FINALS = ("Loaded **1hck** as a cartoon on a white background.",
                       "The radius of gyration is 20.84 Å.")
REASONING_1 = "The user wants the atom count. A selection of all atoms gives it."
REASONING_2 = "The selection reported 2442 atoms, so that is the answer."
TURN_RETRY_STREAMED = "Loading 1hLoading 1hck now."
TURN_RETRY_SEALED = "Loading 1hck now."
LOOP_GUARD_WRAP_UP = ("I could not color by residue type: VMD rejected `mol modcolor 0 top ResidueType` "
                      "four times, so the scene is unchanged. The coloring method is called `ResType`; "
                      "try `mol modcolor 0 top ResType`.")


def update_goldens() -> bool:
    return os.environ.get("CHATVMD_UPDATE_GOLDENS") == "1"


def fixture_path(name: str) -> Path:
    return EVENTS_DIR / ("%s.jsonl" % name)


def dumps(events: Sequence[Dict[str, Any]]) -> str:
    """One ASCII JSON envelope per line, keys sorted."""
    return "".join(json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n" for event in events)


def read_fixture(name: str) -> List[Dict[str, Any]]:
    text = fixture_path(name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def generate(name: str, work: Path) -> List[Dict[str, Any]]:
    """Run scenario ``name`` against a fresh RuntimeApp rooted in ``work``; normalised events."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    return normalise(_BUILDERS[name](work), work)


# --- running a scenario ------------------------------------------------------

@contextlib.contextmanager
def _recorder_off() -> Iterator[None]:
    """No .vmdai_runs run directories (request.finished.run_dir is then null)."""
    old = os.environ.get("VMD_AI_RECORDER")
    os.environ["VMD_AI_RECORDER"] = "off"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("VMD_AI_RECORDER", None)
        else:
            os.environ["VMD_AI_RECORDER"] = old


def _usage(evaluated: int, out: int) -> Dict[str, Any]:
    return {"input_tokens_evaluated": evaluated, "output_tokens": out, "cache_read_tokens": None,
            "source": "ollama"}


def _run_requests(work: Path, script: List[ScriptTurn], results: List[Any], prompts: Sequence[str],
                  *, wrap_up_text: str = "") -> List[Dict[str, Any]]:
    with _recorder_off():
        app = make_token_app(work)
        app.claude_loop = MetaScriptedLoop(script, wrap_up_text=wrap_up_text)
        app.tool_bridge = ProductBridge(results)
        session = start_v2(app, work)
        for prompt in prompts:
            result(send(app, session, prompt))
            wait_idle(app, session, timeout=10.0)
        return poll_all(app, session)


def _poll_until(app, session, predicate: Callable[[Dict[str, Any]], bool],
                timeout: float = 10.0) -> List[Dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = poll_all(app, session)
        if any(predicate(event) for event in events):
            return events
        time.sleep(0.01)
    raise AssertionError("the scenario never reached the expected event")


def _local(kind: str, **fields: Any) -> Dict[str, Any]:
    """A plugin-local event (never sent by the runtime, so seq 0)."""
    metadata: Dict[str, Any] = {"kind": kind, "v": 2}
    metadata.update(fields)
    return {"seq": 0, "ts": 0.0, "role": "system", "type": "state", "text": "", "metadata": metadata}


# --- the five scenarios ------------------------------------------------------

def _conversation(work: Path) -> List[Dict[str, Any]]:
    """Two requests: prose, a command that works, a failing then recovered command, a snapshot, answers."""
    image = {"path": str(SNAPSHOT_PNG), "thumb_path": str(SNAPSHOT_PNG), "width": 847, "height": 1024,
             "src_width": 1280, "src_height": 1547, "renderer": "TachyonInternal"}
    failed = {"index": 2, "text": "display backgroundcolor white",
              "error_info": 'display: invalid option "backgroundcolor"\n    while executing\n'
                            '"display backgroundcolor white"'}
    script = [
        ScriptTurn(text="I'll load 1hck and show it as a cartoon.",
                   tool_blocks=[run_cmd("tc_1", "mol new 1hck.pdb\nmol delrep 0 top\n"
                                        "mol representation NewCartoon\nmol addrep top",
                                        "Load the structure and draw it as a cartoon.")],
                   usage=_usage(5120, 61)),
        ScriptTurn(tool_blocks=[run_cmd("tc_2", "color Display Background white\ndisplay backgroundcolor white",
                                        "Make the background white.")], usage=_usage(5390, 38)),
        ScriptTurn(text="`display backgroundcolor` does not exist; the color command alone is enough.",
                   tool_blocks=[run_cmd("tc_3", "color Display Background white",
                                        "Set the background with the supported command.")],
                   usage=_usage(5520, 44)),
        ScriptTurn(tool_blocks=[tool_block("tc_4", "capture_vmd_snapshot", purpose="check the cartoon")],
                   usage=_usage(5610, 20)),
        ScriptTurn(text=CONVERSATION_FINALS[0], usage=_usage(6710, 25)),
        ScriptTurn(tool_blocks=[run_cmd("tc_5", "set sel [atomselect top protein]\nmeasure rgyr $sel",
                                        "Radius of gyration of the protein.")], usage=_usage(6900, 35)),
        ScriptTurn(text=CONVERSATION_FINALS[1], usage=_usage(7010, 14)),
    ]
    results = [
        product_result(statements={"total": 4, "applied": 4, "failed": None}, duration_ms=412),
        product_result(ok=False, error='display: invalid option "backgroundcolor"',
                       applied_text="color Display Background white\n",
                       statements={"total": 2, "applied": 1, "failed": failed}, duration_ms=38),
        product_result(statements={"total": 1, "applied": 1, "failed": None}, duration_ms=12),
        product_result(image=image, duration_ms=930),
        product_result(output="20.8431", statements={"total": 2, "applied": 2, "failed": None}, duration_ms=25),
    ]
    return _run_requests(work, script, results, CONVERSATION_PROMPTS)


def _dead_runtime(work: Path) -> List[Dict[str, Any]]:
    """request.started and tool.started, then the runtime dies: local notices, no request.finished."""
    gate = threading.Event()

    def never_answers(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        gate.wait(10)
        return product_result(ok=False, executed="unknown", error="stopped while running; outcome unknown")

    script = [ScriptTurn(text="Loading 1hck.", tool_blocks=[run_cmd("tc_1", "mol new 1hck.pdb", "Load it.")],
                         usage=_usage(5120, 30))]
    with _recorder_off():
        app = make_token_app(work)
        app.claude_loop = MetaScriptedLoop(script)
        app.tool_bridge = ProductBridge([never_answers])
        session = start_v2(app, work)
        result(send(app, session, "load 1hck"))
        events = _poll_until(app, session, lambda e: (e.get("metadata") or {}).get("kind") == "tool.started")
        # The runtime "dies" here: nothing it pushes after tool.started is recorded.
        call(app, "chat.cancel", {}, session)
        gate.set()
        wait_idle(app, session, timeout=10.0)
    request_id = next(e["metadata"]["request_id"] for e in events
                      if e["metadata"].get("kind") == "request.started")
    return events + [
        _local("local.connection", state="reconnecting", detail="Runtime not reachable; retry in 0.5 s",
               request_lost=False),
        _local("local.send_failed", code="transport", message="Runtime not reachable"),
        _local("local.connection", state="ready", detail="Reconnected to a new runtime", request_lost=True),
        _local("local.request_ended", request_id=request_id),
    ]


def _reasoning_answer(work: Path) -> List[Dict[str, Any]]:
    """Reasoning in two turns: the reasoning->tool and reasoning->answer boundaries."""
    script = [
        ScriptTurn(reasoning=REASONING_1,
                   tool_blocks=[run_cmd("tc_1", "set sel [atomselect top all]\n$sel num", "Count the atoms.")],
                   usage=_usage(5120, 48)),
        ScriptTurn(reasoning=REASONING_2, text="1hck has 2442 atoms.", usage=_usage(5260, 22)),
    ]
    results = [product_result(output="2442", statements={"total": 2, "applied": 2, "failed": None},
                              duration_ms=18)]
    return _run_requests(work, script, results, ("how many atoms does 1hck have?",))


def _turn_retry(work: Path) -> List[Dict[str, Any]]:
    """A stream that drops mid-turn: the partial block is discarded and the turn retried once."""
    script = [
        ScriptTurn(text="Loading 1h", drop_after_text=True),
        ScriptTurn(text=TURN_RETRY_SEALED, tool_blocks=[run_cmd("tc_1", "mol new 1hck.pdb", "Load it.")],
                   usage=_usage(5120, 30)),
        ScriptTurn(text="Done: 1hck is loaded.", usage=_usage(5200, 12)),
    ]
    results = [product_result(output="0", statements={"total": 1, "applied": 1, "failed": None}, duration_ms=35)]
    return _run_requests(work, script, results, ("load 1hck",))


def _loop_guard(work: Path) -> List[Dict[str, Any]]:
    """C4: the same failing call four times: nudge on the third, stop and wrap up on the fourth."""
    def same(n: int) -> Dict[str, Any]:
        return run_cmd("tc_%d" % n, "mol modcolor 0 top ResidueType", "Color by residue type.")

    error = 'mol modcolor: invalid coloring method "ResidueType"'
    fail = product_result(ok=False, error=error, duration_ms=9,
                          statements={"total": 1, "applied": 0,
                                      "failed": {"index": 1, "text": "mol modcolor 0 top ResidueType",
                                                 "error_info": error}})
    script = [
        ScriptTurn(text="Coloring by residue type.", tool_blocks=[same(1)], usage=_usage(5120, 30)),
        ScriptTurn(tool_blocks=[same(2)], usage=_usage(5300, 26)),
        ScriptTurn(tool_blocks=[same(3)], usage=_usage(5480, 26)),
        ScriptTurn(tool_blocks=[same(4)], usage=_usage(5660, 26)),
    ]
    return _run_requests(work, script, [fail, fail, fail, fail], ("color the protein by residue type",),
                         wrap_up_text=LOOP_GUARD_WRAP_UP)


_BUILDERS: Dict[str, Callable[[Path], List[Dict[str, Any]]]] = {
    "03_conversation": _conversation,
    "11_dead_runtime": _dead_runtime,
    "reasoning_answer": _reasoning_answer,
    "turn_retry": _turn_retry,
    "loop_guard": _loop_guard,
}


# --- normalisation -----------------------------------------------------------

_ID_FAMILIES = (
    (re.compile(r"req_[0-9a-f]{12}"), "req_%012d"),
    (re.compile(r"chat_[0-9a-f]{12}"), "chat_%012d"),
    (re.compile(r"sess_[0-9a-f]{12}"), "sess_%012d"),
)


def normalise(events: Sequence[Dict[str, Any]], work: Path) -> List[Dict[str, Any]]:
    """Make a scenario's events identical across runs and machines (see the module docstring)."""
    out = copy.deepcopy(list(events))
    names: Dict[str, str] = {}
    counters: Dict[str, int] = {}

    def name_for(raw: str, template: str) -> str:
        if raw not in names:
            counters[template] = counters.get(template, 0) + 1
            names[raw] = template % counters[template]
        return names[raw]

    for event in out:                                     # call keys, in order of appearance
        key = (event.get("metadata") or {}).get("call_key")
        if isinstance(key, str) and key:
            name_for(key, "%012d")
    call_keys = dict(names)
    roots = sorted({str(work), os.path.realpath(str(work))}, key=len, reverse=True)

    def fix(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fix(v) for v in value]
        if not isinstance(value, str):
            return value
        if value in call_keys:
            return call_keys[value]
        for pattern, template in _ID_FAMILIES:
            value = pattern.sub(lambda m, t=template: name_for(m.group(0), t), value)
        for root in roots:
            value = value.replace(root, "@WORK@")
        return value.replace(str(REPO), "@REPO@")

    out = [fix(event) for event in out]
    start_line: Dict[Any, int] = {}
    for index, event in enumerate(out):
        event["ts"] = round(BASE_TS + STEP_S * index, 3)
        meta = event.get("metadata") or {}
        kind = meta.get("kind")
        if kind == "tool.started":
            start_line[("tool", meta.get("call_key"))] = index
        elif kind == "request.started":
            start_line[("request", meta.get("request_id"))] = index
        elif event.get("role") == "reasoning" and event.get("type") == "chunk":
            start_line.setdefault(("reasoning", meta.get("request_id"), meta.get("turn")), index)
        if "duration_ms" in meta:
            if kind == "tool.finished":
                begin = start_line.get(("tool", meta.get("call_key")), index)
            elif kind == "request.finished":
                begin = start_line.get(("request", meta.get("request_id")), index)
            elif event.get("role") == "reasoning":
                begin = start_line.get(("reasoning", meta.get("request_id"), meta.get("turn")), index)
            else:
                begin = index
            meta["duration_ms"] = int(round((index - begin) * STEP_S * 1000))
    return out
