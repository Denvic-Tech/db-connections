from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ConnectionCheckResult:
    name: str
    connected: bool
    message: str | None = None
    exception: str | None = None
