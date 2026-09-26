"""launch.py - launch token, token file and READY line (§2e, §2d).

The runtime makes a 128-bit launch token at start. Under --announce it is
printed once, in the READY line on stdout. Otherwise (attach mode) it is
written to ~/.vmdai/run/runtime-<port>.json with mode 0600 and removed on a
clean exit. Stdlib only; imports on Python 3.9.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, Optional

READY_PREFIX = "VMDAI_READY "


def generate_launch_token() -> str:
    """128 random bits as 32 lowercase hex characters."""
    return secrets.token_hex(16)


def token_file_path(port: int, home: Optional[str] = None) -> Path:
    base = Path(home) if home is not None else Path(os.path.expanduser("~"))
    return base / ".vmdai" / "run" / f"runtime-{int(port)}.json"


def write_token_file(
    port: int,
    pid: int,
    token: str,
    protocol: int = 2,
    home: Optional[str] = None,
) -> Path:
    """Write {port, pid, token, protocol} with mode 0600, atomically."""
    path = token_file_path(port, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(path.parent), 0o700)
    except OSError:
        pass
    payload = json.dumps({
        "port": int(port),
        "pid": int(pid),
        "token": str(token),
        "protocol": int(protocol),
    })
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # the umask may have narrowed it; never widen past 0600
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(payload)
    os.replace(str(tmp), str(path))
    return path


def read_token_file(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="ascii"))


def remove_token_file(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def format_ready_line(port: int, pid: int, version: str, protocol: int, launch_token: str) -> str:
    """VMDAI_READY {"port":…,"pid":…,"version":…,"protocol":2,"launch_token":…}"""
    payload = {
        "port": int(port),
        "pid": int(pid),
        "version": str(version),
        "protocol": int(protocol),
        "launch_token": str(launch_token),
    }
    return READY_PREFIX + json.dumps(payload, separators=(",", ":"))
