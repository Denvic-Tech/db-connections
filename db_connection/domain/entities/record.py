from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from typing import Any

from .envelope import ConnectionEnvelope


@dataclass(slots=True, kw_only=True)
class StoredConnectionIssue:
    field: str
    code: str
    message: str
    details: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class ConnectionRecord(ConnectionEnvelope):
    id: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    read_issues: list[StoredConnectionIssue] = dataclass_field(default_factory=list)
    raw_properties: Any | None = None
    raw_driver_options: Any | None = None
    raw_secrets: Any | None = None

    def has_read_issue(self, code: str, *, field_name: str | None = None) -> bool:
        return any(
            issue.code == code and (field_name is None or issue.field == field_name) for issue in self.read_issues
        )
