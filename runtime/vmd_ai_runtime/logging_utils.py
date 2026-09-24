from __future__ import annotations

import logging
import os
import re
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)(session[_-]?token\s*[=:]\s*)([^\s,;]+)"),
]


def redact_sensitive(value: Any) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("vmd_ai_runtime")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[vmd_ai_runtime] %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    return logger


def env_or_default(name: str, default: str) -> str:
    return os.getenv(name, default)
