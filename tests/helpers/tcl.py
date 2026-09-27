"""One place that decides how Tcl tests run and when they skip (spec §6, C9).

Interpreter: VMD_AI_TCLSH (from the live_env snapshot) if set, else the first
``tclsh8.6``/``tclsh`` on PATH whose ``info patchlevel`` is 8.6.x.  An 8.5
tclsh (macOS /usr/bin) can't load http 2.9 and is rejected.

Packages: http 2.9.5 from VMD.app's Tcl.framework module path (or
VMD_AI_TCL_TM); json 1.1.2 from plugin/lib/json once M1 vendors it, else
from VMD's plugins/noarch/tcl/json1.0.
"""
from __future__ import annotations

import concurrent.futures
import functools
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pytest

from helpers.live import LIVE_ENV

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugin"
PLUGIN_JSON_DIR = PLUGIN_DIR / "lib" / "json"
VMD_TCL_TM_DIR = (
    "/Applications/VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/tcl8/8.6"
)
VMD_JSON_DIR = "/Applications/VMD.app/Contents/vmd/plugins/noarch/tcl/json1.0"
HTTP_VERSION = "2.9.5"
JSON_VERSION = "1.1.2"
TCLSH_NAMES = ("tclsh8.6", "tclsh")

_SUMMARY_RE = re.compile(
    r"^\S*:\s+Total\s+(\d+)\s+Passed\s+(\d+)\s+Skipped\s+(\d+)\s+Failed\s+(\d+)",
    re.MULTILINE,
)


@dataclass
class TclTestResult:
    passed: int
    failed: int
    skipped: int
    output: str


@functools.lru_cache(maxsize=None)
def _patchlevel(executable: str) -> Optional[str]:
    """``info patchlevel`` of ``executable``, or None if it can't be run."""
    try:
        proc = subprocess.run(
            [executable],
            input="puts [info patchlevel]\nexit 0\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    level = proc.stdout.strip()
    return level or None


def _is_86(executable: str) -> bool:
    level = _patchlevel(executable)
    return bool(level) and level.startswith("8.6.")


@functools.lru_cache(maxsize=None)
def _has_tcltest(executable: str) -> bool:
    try:
        proc = subprocess.run(
            [executable],
            input="puts [package require tcltest 2]\nexit 0\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and proc.stdout.strip().startswith("2.")


def _path_candidates(path_value: str) -> Iterable[str]:
    for directory in path_value.split(os.pathsep):
        if not directory:
            continue
        for name in TCLSH_NAMES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                yield candidate


def find_tclsh() -> Optional[str]:
    override = LIVE_ENV.get("VMD_AI_TCLSH")
    if override:
        return override if _is_86(override) else None
    for candidate in _path_candidates(os.environ.get("PATH", "")):
        if _is_86(candidate):
            return candidate
    return None


def http_tm_dir() -> Optional[str]:
    directory = LIVE_ENV.get("VMD_AI_TCL_TM") or VMD_TCL_TM_DIR
    if Path(directory, f"http-{HTTP_VERSION}.tm").is_file():
        return directory
    return None


def json_pkg_dir() -> Optional[str]:
    for directory in (PLUGIN_JSON_DIR, Path(VMD_JSON_DIR)):
        if (directory / "pkgIndex.tcl").is_file() and (directory / "json.tcl").is_file():
            return str(directory)
    return None


def tcl_skip_reason(*, needs_http: bool = False, needs_json: bool = False) -> Optional[str]:
    if find_tclsh() is None:
        return (
            "no Tcl 8.6 interpreter: set VMD_AI_TCLSH or put tclsh8.6 on PATH "
            "(an 8.5 tclsh such as /usr/bin/tclsh is rejected)"
        )
    if needs_http and http_tm_dir() is None:
        return (
            f"http {HTTP_VERSION} not found: set VMD_AI_TCL_TM to the directory holding "
            f"http-{HTTP_VERSION}.tm (VMD.app: {VMD_TCL_TM_DIR})"
        )
    if needs_json and json_pkg_dir() is None:
        return (
            f"json {JSON_VERSION} not found in {PLUGIN_JSON_DIR} or {VMD_JSON_DIR}"
        )
    return None


def requires_tcl(*, needs_http: bool = False, needs_json: bool = False):
    reason = tcl_skip_reason(needs_http=needs_http, needs_json=needs_json)
    return pytest.mark.skipif(reason is not None, reason=reason or "")


def tcl_word(value: str) -> str:
    """Quote ``value`` as one Tcl word (paths may contain spaces)."""
    if value and re.fullmatch(r"[A-Za-z0-9_./:+=@%,-]+", value):
        return value
    if not re.search(r"[{}\\]", value):
        return "{" + value + "}"
    return '"' + re.sub(r'([\\"$\[\]{}])', r"\\\1", value) + '"'


def tcl_prelude(*, needs_http: bool = False, needs_json: bool = False) -> str:
    lines: List[str] = []
    if needs_http:
        tm_dir = http_tm_dir()
        if tm_dir is None:
            raise RuntimeError(tcl_skip_reason(needs_http=True) or "http missing")
        lines.append(f"::tcl::tm::path add {tcl_word(tm_dir)}")
        lines.append(f"package require -exact http {HTTP_VERSION}")
    if needs_json:
        json_dir = json_pkg_dir()
        if json_dir is None:
            raise RuntimeError(tcl_skip_reason(needs_json=True) or "json missing")
        lines.append(f"lappend auto_path {tcl_word(json_dir)}")
        lines.append(f"package require -exact json {JSON_VERSION}")
    return "".join(line + "\n" for line in lines)


def _merged_env(home: str, env: Optional[Dict[str, str]]) -> Dict[str, str]:
    merged = dict(os.environ)
    merged.update(
        HOME=home,
        VMDAI_REPO=str(REPO),
        VMDAI_PLUGIN_DIR=str(PLUGIN_DIR),
    )
    if env:
        merged.update(env)
    return merged


def run_tcl(
    script: str,
    *,
    needs_http: bool = False,
    needs_json: bool = False,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Run ``script`` (after the package prelude) as a file under tclsh 8.6.

    Skips the calling test when the interpreter or a package is missing.
    """
    reason = tcl_skip_reason(needs_http=needs_http, needs_json=needs_json)
    if reason is not None:
        pytest.skip(reason)
    tclsh = find_tclsh()
    assert tclsh is not None
    with tempfile.TemporaryDirectory(prefix="vmdai_tcl_") as tmp:
        home = os.path.join(tmp, "home")
        os.mkdir(home)
        path = os.path.join(tmp, "script.tcl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(tcl_prelude(needs_http=needs_http, needs_json=needs_json))
            fh.write(script)
        return subprocess.run(
            [tclsh, path],
            cwd=cwd or tmp,
            env=_merged_env(home, env),
            capture_output=True,
            text=True,
            timeout=timeout,
        )


def run_tcltest(
    test_file: str,
    *,
    needs_http: bool = False,
    needs_json: bool = False,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 120,
    prelude: str = "",
) -> TclTestResult:
    """Source a tcltest file under tclsh 8.6 and return its summary counts.

    The file must end with ``::tcltest::cleanupTests``.  It sees
    ``$env(VMDAI_REPO)``, ``$env(VMDAI_PLUGIN_DIR)`` and a temp ``$env(HOME)``.
    A file that dies before printing a summary counts as one failure.
    """
    reason = tcl_skip_reason(needs_http=needs_http, needs_json=needs_json)
    if reason is not None:
        pytest.skip(reason)
    tclsh = find_tclsh()
    assert tclsh is not None
    if not _has_tcltest(tclsh):
        pytest.skip(f"tcltest 2 is not available in {tclsh}")
    test_path = Path(test_file).resolve()
    with tempfile.TemporaryDirectory(prefix="vmdai_tcltest_") as tmp:
        home = os.path.join(tmp, "home")
        os.mkdir(home)
        outfile = os.path.join(tmp, "tcltest.out")
        driver = os.path.join(tmp, "driver.tcl")
        with open(driver, "w", encoding="utf-8") as fh:
            fh.write(tcl_prelude(needs_http=needs_http, needs_json=needs_json))
            fh.write(prelude if prelude.endswith("\n") or not prelude else prelude + "\n")
            fh.write("package require tcltest 2\n")
            fh.write(f"::tcltest::configure -outfile {tcl_word(outfile)} -verbose {{body error}}\n")
            fh.write(f"source {tcl_word(str(test_path))}\n")
        proc = subprocess.run(
            [tclsh, driver],
            cwd=tmp,
            env=_merged_env(home, env),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        report = Path(outfile).read_text(encoding="utf-8") if os.path.exists(outfile) else ""
    output = report + proc.stdout + proc.stderr
    match = _SUMMARY_RE.search(report)
    if match is None:
        return TclTestResult(passed=0, failed=1, skipped=0, output=output)
    _total, passed, skipped, failed = (int(g) for g in match.groups())
    return TclTestResult(passed=passed, failed=failed, skipped=skipped, output=output)


# --- once-per-module tcltest runs, overlapped ---------------------------------
#
# A tcltest module's module-scoped fixture runs one subprocess that mostly
# waits (timers, child processes, sockets). Each such module registers that
# work with @module_run; its fixture returns module_result(request). The first
# of these fixtures a session reaches runs every registered module that has
# selected tests, each on its own thread, and waits for all of them; later
# fixtures take their stored outcome. The runs overlap only each other: the
# test thread waits meanwhile, so no test body, monkeypatch or hermetic
# environment is active during a run, just as when each module fixture ran on
# its own. Each run is still exactly one run per module, and an exception
# (a failure or pytest.skip) is re-raised by that module's own fixture.
#
# Run bodies do execute concurrently with each other, on worker threads. A
# run body must therefore not touch process-wide state (os.environ, the cwd,
# signal handlers, module globals), must pass its environment to the
# subprocess explicitly, and must use its own tmp_path_factory.mktemp prefix.
# A module that needs per-test hermetic state or global patches keeps a
# plain fixture instead.

ModuleRun = Callable[[pytest.TempPathFactory], Any]

_MODULE_RUNS: Dict[str, ModuleRun] = {}
_MODULE_OUTCOMES: Dict[str, Tuple[bool, Any]] = {}


def module_run(fn: ModuleRun) -> ModuleRun:
    """Register ``fn(tmp_path_factory)`` as its module's once-per-module run."""
    _MODULE_RUNS[fn.__module__] = fn
    return fn


def _outcome(fn: ModuleRun, factory: pytest.TempPathFactory) -> Tuple[bool, Any]:
    try:
        return True, fn(factory)
    except BaseException as exc:  # noqa: BLE001 - pytest.skip and failures alike
        return False, exc


def _run_pending(request: pytest.FixtureRequest) -> None:
    selected = {getattr(item, "module", None) for item in request.session.items}
    selected_names = {module.__name__ for module in selected if module is not None}
    names = [name for name in _MODULE_RUNS
             if name not in _MODULE_OUTCOMES
             and (name in selected_names or name == request.module.__name__)]
    factory = request.getfixturevalue("tmp_path_factory")
    factory.getbasetemp()  # create the base temp dir before the threads use it
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(names)),
                                               thread_name_prefix="tcltest") as pool:
        futures = {name: pool.submit(_outcome, _MODULE_RUNS[name], factory) for name in names}
        for name, future in futures.items():
            _MODULE_OUTCOMES[name] = future.result()


def module_result(request: pytest.FixtureRequest) -> Any:
    """The calling module's @module_run result; runs the pending ones first."""
    name = request.module.__name__
    if name not in _MODULE_RUNS:
        raise RuntimeError(f"{name} has no @module_run function")
    if name not in _MODULE_OUTCOMES:
        _run_pending(request)
    ok, value = _MODULE_OUTCOMES[name]
    if not ok:
        raise value
    return value
