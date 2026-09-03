from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from ..drivers import DriverOptionsBase
from .draft import ConnectionDraft


@dataclass(slots=True)
class ValidatedConnection:
    name: str
    kind: str
    type: str
    driver: str | None
    driver_options: DriverOptionsBase | None
    properties: BaseModel
    secrets: BaseModel | None
    labels: dict[str, str]
    metadata: dict[str, Any]
    extra: dict[str, Any]

    def to_draft(self) -> ConnectionDraft:
        return ConnectionDraft(
            name=self.name,
            kind=self.kind,
            type=self.type,
            driver=self.driver,
            driver_options=self.driver_options,
            properties=self.properties.model_dump(mode="json"),
            secrets={} if self.secrets is None else self.secrets.model_dump(mode="json"),
            labels=dict(self.labels),
            metadata=dict(self.metadata),
            extra=dict(self.extra),
        )
