"""runtime.tcl: launch, READY, attach and stop against stub processes (P06-T05).

Runs tests/tcl/test_runtime_launch.tcl once with HOME, the Python wrapper and
the stub runtime all under paths that contain spaces.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import List

import pytest

from helpers.fake_rpc_server import FakeRpcServer, Recorded
from helpers.tcl import REPO, TclTestResult, run_tcltest
from vmd_ai_runtime.launch import write_token_file

TCL_FILE = REPO / "tests" / "tcl" / "test_runtime_launch.tcl"
STUBS = REPO / "tests" / "fixtures" / "stub_runtime"
TOTAL = 14
TOKEN = "0123456789abcdef0123456789abcdef"


@dataclass
class LaunchRun:
    result: TclTestResult
    attach_requests: List[Recorded]
    sleeper_alive_after: bool


def _kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


@pytest.fixture(scope="module")
def launch_run(tmp_path_factory) -> LaunchRun:
    base = tmp_path_factory.mktemp("launch")
    home = base / "home dir"
    home.mkdir()
    py_dir = base / "py dir"
    py_dir.mkdir()
    python = py_dir / "python3"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    stub_dir = base / "stub dir"
    stub_dir.mkdir()
    shutil.copy(STUBS / "ready_runtime.py", stub_dir / "ready runtime.py")
    shutil.copy(STUBS / "fail_runtime.py", stub_dir / "fail_runtime.py")
    pid_log = base / "pids.txt"
    pid_log.write_text("")
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    health = {"ok": True, "pid": sleeper.pid, "version": "0.3.0", "protocol": 2}
    try:
        with FakeRpcServer(health=health) as attach, FakeRpcServer(health={"ok": True}) as old:
            write_token_file(attach.port, sleeper.pid, TOKEN, 2, home=str(home))
            env = {
                "HOME": str(home),
                "VMD_AI_PYTHON": str(python),
                "VMDAI_STUB_DIR": str(stub_dir),
                "VMDAI_ATTACH_PORT": str(attach.port),
                "VMDAI_OLD_PORT": str(old.port),
                "VMDAI_TOKEN": TOKEN,
                "VMDAI_SLEEPER_PID": str(sleeper.pid),
                "VMDAI_PID_LOG": str(pid_log),
            }
            result = run_tcltest(str(TCL_FILE), env=env, timeout=120)
            requests = list(attach.requests)
        return LaunchRun(result, requests, sleeper.poll() is None)
    finally:
        for line in pid_log.read_text().split():
            _kill_quietly(int(line))
        sleeper.kill()
        sleeper.wait()


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(launch_run):
    assert (launch_run.result.passed, launch_run.result.failed) == (TOTAL, 0), launch_run.result.output


def test_ready_parsed(launch_run):
    _assert_passed(launch_run.result, ["rt-ready-1"])


def test_ready_after_noise(launch_run):
    _assert_passed(launch_run.result, ["rt-noise-1"])


def test_stderr_then_exit_didnt_start_with_tail(launch_run):
    _assert_passed(launch_run.result, ["rt-fail-1", "rt-fail-2"])


def test_ready_timeout(launch_run):
    _assert_passed(launch_run.result, ["rt-timeout-1"])


def test_attach_reads_token_file(launch_run):
    _assert_passed(launch_run.result, ["rt-attach-1", "rt-attach-2", "rt-attach-3"])


def test_too_old_protocol(launch_run):
    _assert_passed(launch_run.result, ["rt-old-1", "rt-old-2"])


def test_stop_owned_escalates_never_attached(launch_run):
    _assert_passed(launch_run.result, ["rt-stop-1", "rt-stop-2", "rt-stop-3"])
    assert [r for r in launch_run.attach_requests if r.method == "runtime.shutdown"] == []
    assert launch_run.sleeper_alive_after


def test_paths_with_spaces(launch_run):
    _assert_passed(launch_run.result, ["rt-spaces-1"])
