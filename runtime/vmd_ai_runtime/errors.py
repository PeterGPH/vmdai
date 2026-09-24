from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class RpcError(Exception):
    code: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    http_status: int = 200

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
