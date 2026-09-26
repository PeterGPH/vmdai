from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
from typing import Any, Optional

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)(session[_-]?token\s*[=:]\s*)([^\s,;]+)"),
]

# ~/.vmdai/logs/runtime.log rotates at 2 MiB and keeps three old files (§7 Logs).
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3
_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_STDERR_FORMAT = "[vmd_ai_runtime] %(levelname)s %(message)s"
_MARK = "_vmdai_handler"  # set on the handlers configure_logging installs


def redact_sensitive(value: Any) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def default_log_path(home: Optional[str] = None) -> str:
    """~/.vmdai/logs/runtime.log (or under ``home``)."""
    base = home if home is not None else os.path.expanduser("~")
    return os.path.join(base, ".vmdai", "logs", "runtime.log")


def configure_logging(
    level: str = "INFO",
    *,
    log_path: Optional[str] = None,
    stderr: bool = True,
) -> logging.Logger:
    """Configure logging for the runtime process and return its logger.

    The handlers go on the root logger, so records from ``vmd_ai_runtime``
    and from ``vmdai.*`` (claude_loop, tool_bridge, wiki_store) all reach
    them and none falls through to ``logging.lastResort``, which would
    print onto the plugin's READY pipe (§2d). ``stderr=False`` (used under
    --announce) installs no stream handler at all. Calling this again
    replaces the handlers an earlier call installed.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)
            handler.close()

    installed = []
    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        installed.append(file_handler)
    if stderr:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(logging.Formatter(_STDERR_FORMAT))
        installed.append(stream_handler)
    if not installed:
        # A handler must exist, or warnings would reach lastResort (stderr).
        installed.append(logging.NullHandler())
    for handler in installed:
        setattr(handler, _MARK, True)
        root.addHandler(handler)

    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger = logging.getLogger("vmd_ai_runtime")
    logger.setLevel(logging.NOTSET)  # inherit the root level
    return logger


def env_or_default(name: str, default: str) -> str:
    return os.getenv(name, default)
