from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    kind: str
    type: str
    driver: str | None = None
    driver_options: dict[str, Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    driver: str | None = None
    driver_options: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    labels: dict[str, str] | None = None
    metadata: dict[str, Any] | None = None


class ConnectionReadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    kind: str
    type: str
    driver: str | None = None
    driver_options: dict[str, Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class ConnectionIssueResponse(BaseModel):
    field: str
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class BrokenConnectionReadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: Literal["invalid"] = "invalid"
    id: str
    name: str
    kind: str
    type: str
    driver: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    issues: list[ConnectionIssueResponse] = Field(default_factory=list)
    raw_properties: Any | None = None
    raw_driver_options: Any | None = None
    raw_secrets: Any | None = None


class ConnectionKindInfoResponse(BaseModel):
    name: str
    description: str
    capabilities: list[str] | None = None


class ConnectionDriverInfoResponse(BaseModel):
    name: str
    options_schema: dict[str, Any]
    public_options_schema: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)


class ConnectionTypeInfoResponse(BaseModel):
    name: str
    kind: str
    default_driver: str | None = None
    drivers: list[ConnectionDriverInfoResponse] = Field(default_factory=list)
    supported_drivers: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    properties_schema: dict[str, Any]
    secrets_schema: dict[str, Any] | None = None
    public_schema: dict[str, Any] | None = None
