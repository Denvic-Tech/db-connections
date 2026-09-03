from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(slots=True)
class ConnectionListQuery:
    kind: str | None = None
    type: str | None = None
    name: str | None = None
    include_deleted: bool = False
    label_filters: dict[str, str] = field(default_factory=dict)
    metadata_filters: dict[str, Any] = field(default_factory=dict)
    extra_filters: dict[str, Any] = field(default_factory=dict)

    def model_copy(self, *, update: dict[str, Any] | None = None) -> ConnectionListQuery:
        return replace(self, **(update or {}))
