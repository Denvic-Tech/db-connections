from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..drivers import DriverOptionsBase
from ..types import DefaultConnectionKinds, DefaultConnectionTypes


@dataclass(slots=True, kw_only=True)
class ConnectionEnvelope:

    name: str
    kind: DefaultConnectionKinds | str
    type: DefaultConnectionTypes | str
    driver: str | None = None
    driver_options: dict[str, Any] | DriverOptionsBase | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
