from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from ..domain.drivers import DriverOptionsBase
from ..domain.entities import ConnectionRecord, StoredConnectionIssue
from ..errors import ConnectionTypeNotSupportedError, ValidationFailedError
from ..registry.base import ConnectionRegistry
from ._driver_options import build_public_driver_options


@dataclass(slots=True)
class PublicConnectionView:
    id: str
    name: str
    kind: str
    type: str
    driver: str | None
    driver_options: BaseModel | None
    properties: BaseModel
    labels: dict[str, str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    extra: dict[str, Any]


@dataclass(slots=True)
class BrokenPublicConnectionView:
    id: str
    name: str
    kind: str
    type: str
    driver: str | None
    labels: dict[str, str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    extra: dict[str, Any]
    issues: list[StoredConnectionIssue]
    raw_properties: Any | None
    raw_driver_options: Any | None
    raw_secrets: Any | None
    state: str = "invalid"


class ConnectionPublicProjector:
    def __init__(self, registry: ConnectionRegistry) -> None:
        self._registry = registry

    def build(self, record: ConnectionRecord) -> PublicConnectionView:
        spec = self._registry.get_type(record.type)
        try:
            properties = spec.properties_model.model_validate(record.properties)
            public_model = spec.public_model or spec.properties_model
            public_properties = public_model.model_validate(properties.model_dump(mode="python"))
        except ValidationError as exc:
            raise ValidationFailedError(
                "Stored connection payload is invalid.", details={"errors": exc.errors()}
            ) from exc

        effective_driver = record.driver or spec.default_driver
        public_driver_options = build_public_driver_options(
            spec=spec,
            connection_type=record.type,
            effective_driver=effective_driver,
            raw_options=record.driver_options,
        )

        return PublicConnectionView(
            id=record.id,
            name=record.name,
            kind=record.kind,
            type=record.type,
            driver=record.driver,
            driver_options=public_driver_options,
            properties=public_properties,
            labels=dict(record.labels),
            metadata=dict(record.metadata),
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
            extra=dict(record.extra),
        )

    def build_any(self, record: ConnectionRecord) -> PublicConnectionView | BrokenPublicConnectionView:
        issues = list(record.read_issues)
        raw_properties = self._get_raw_properties(record)
        raw_driver_options = self._get_raw_driver_options(record)
        raw_secrets = record.raw_secrets

        try:
            spec = self._registry.get_type(record.type)
        except ConnectionTypeNotSupportedError:
            issues.append(
                StoredConnectionIssue(
                    field="type",
                    code="unknown_type",
                    message="Stored connection type is not registered.",
                    details={"type": record.type},
                )
            )
            return self._build_broken_view(
                record,
                issues=issues,
                raw_properties=raw_properties,
                raw_driver_options=raw_driver_options,
                raw_secrets=raw_secrets,
            )

        if record.kind != spec.kind:
            issues.append(
                StoredConnectionIssue(
                    field="kind",
                    code="kind_mismatch",
                    message="Stored connection kind does not match the registered type.",
                    details={"stored_kind": record.kind, "expected_kind": spec.kind},
                )
            )

        public_properties: BaseModel | None = None
        if not record.has_read_issue("invalid_properties", field_name="properties"):
            try:
                properties = spec.properties_model.model_validate(record.properties)
                public_model = spec.public_model or spec.properties_model
                public_properties = public_model.model_validate(properties.model_dump(mode="python"))
            except ValidationError as exc:
                issues.append(
                    StoredConnectionIssue(
                        field="properties",
                        code="invalid_properties",
                        message="Stored connection properties payload is invalid.",
                        details={"errors": exc.errors()},
                    )
                )

        public_driver_options: BaseModel | None = None
        if not record.has_read_issue("invalid_driver_options", field_name="driver_options"):
            try:
                public_driver_options = build_public_driver_options(
                    spec=spec,
                    connection_type=record.type,
                    effective_driver=record.driver or spec.default_driver,
                    raw_options=record.driver_options,
                )
            except ValidationFailedError as exc:
                issues.append(
                    StoredConnectionIssue(
                        field="driver_options",
                        code="invalid_driver_options",
                        message="Stored connection driver options payload is invalid.",
                        details=exc.details,
                    )
                )

        if (
            spec.secrets_model is not None
            and not record.has_read_issue("unreadable_secrets", field_name="secrets")
            and not record.has_read_issue("invalid_secrets", field_name="secrets")
        ):
            try:
                spec.secrets_model.model_validate(record.secrets)
            except ValidationError as exc:
                issues.append(
                    StoredConnectionIssue(
                        field="secrets",
                        code="invalid_secrets",
                        message="Stored connection secrets payload is invalid.",
                        details={"errors": exc.errors()},
                    )
                )
                raw_secrets = record.secrets

        if issues:
            return self._build_broken_view(
                record,
                issues=issues,
                raw_properties=raw_properties,
                raw_driver_options=raw_driver_options,
                raw_secrets=raw_secrets,
            )

        assert public_properties is not None
        return PublicConnectionView(
            id=record.id,
            name=record.name,
            kind=record.kind,
            type=record.type,
            driver=record.driver,
            driver_options=public_driver_options,
            properties=public_properties,
            labels=dict(record.labels),
            metadata=dict(record.metadata),
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
            extra=dict(record.extra),
        )

    def _build_broken_view(
        self,
        record: ConnectionRecord,
        *,
        issues: list[StoredConnectionIssue],
        raw_properties: Any | None,
        raw_driver_options: Any | None,
        raw_secrets: Any | None,
    ) -> BrokenPublicConnectionView:
        return BrokenPublicConnectionView(
            id=record.id,
            name=record.name,
            kind=record.kind,
            type=record.type,
            driver=record.driver,
            labels=dict(record.labels),
            metadata=dict(record.metadata),
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
            extra=dict(record.extra),
            issues=issues,
            raw_properties=raw_properties,
            raw_driver_options=raw_driver_options,
            raw_secrets=raw_secrets,
        )

    def _get_raw_properties(self, record: ConnectionRecord) -> Any | None:
        return record.raw_properties if record.raw_properties is not None else record.properties

    def _get_raw_driver_options(self, record: ConnectionRecord) -> Any | None:
        if record.raw_driver_options is not None:
            return record.raw_driver_options
        if isinstance(record.driver_options, DriverOptionsBase):
            return record.driver_options.model_dump(mode="python")
        return record.driver_options
