"""P02-T03: rotating file logging on the root logger; no stderr under --announce (§2d, §7)."""
from __future__ import annotations

import logging
import logging.handlers
import subprocess
import sys
from pathlib import Path

import pytest

from vmd_ai_runtime.logging_utils import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    configure_logging,
    default_log_path,
)

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


@pytest.fixture(autouse=True)
def _restore_root_logging():
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def _installed():
    return [h for h in logging.getLogger().handlers if getattr(h, "_vmdai_handler", False)]


def _flush():
    for handler in _installed():
        handler.flush()


def test_file_handler_on_root_captures_vmdai_loggers(tmp_path):
    log = tmp_path / "logs" / "runtime.log"
    configure_logging("INFO", log_path=str(log), stderr=False)
    logging.getLogger("vmdai.claude_loop").warning("loop-warning")
    logging.getLogger("vmdai.tool_bridge").info("bridge-info")
    logging.getLogger("vmd_ai_runtime").info("runtime-info")
    _flush()
    text = log.read_text(encoding="utf-8")
    for needle in ("loop-warning", "bridge-info", "runtime-info", "vmdai.claude_loop"):
        assert needle in text
    assert default_log_path(str(tmp_path)) == str(tmp_path / ".vmdai" / "logs" / "runtime.log")


def test_no_stderr_output_when_disabled(tmp_path):
    log = tmp_path / "runtime.log"
    code = "\n".join([
        "import logging, sys",
        f"sys.path.insert(0, {str(RUNTIME)!r})",
        "from vmd_ai_runtime.logging_utils import configure_logging",
        f"configure_logging('INFO', log_path={str(log)!r}, stderr=False)",
        "logging.getLogger('vmdai.claude_loop').warning('vmdai-warning')",
        "logging.getLogger('vmd_ai_runtime').error('runtime-error')",
    ])
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert proc.stderr == ""
    text = log.read_text(encoding="utf-8")
    assert "vmdai-warning" in text and "runtime-error" in text


def test_rotating_handler_limits(tmp_path):
    log = tmp_path / "deep" / "dir" / "runtime.log"
    configure_logging("INFO", log_path=str(log), stderr=False)
    rotating = [h for h in _installed() if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == LOG_MAX_BYTES == 2 * 1024 * 1024
    assert rotating[0].backupCount == LOG_BACKUP_COUNT == 3
    assert log.parent.is_dir()


def test_idempotent(tmp_path):
    log = tmp_path / "runtime.log"
    configure_logging("INFO", log_path=str(log), stderr=True)
    logger = configure_logging("DEBUG", log_path=str(log), stderr=True)
    assert logger.name == "vmd_ai_runtime"
    assert logger.handlers == []  # records propagate to root, so no duplicate lines
    assert sorted(type(h).__name__ for h in _installed()) == ["RotatingFileHandler", "StreamHandler"]
    assert logging.getLogger().level == logging.DEBUG
    logging.getLogger("vmdai.claude_loop").warning("exactly-once")
    _flush()
    assert log.read_text(encoding="utf-8").count("exactly-once") == 1
