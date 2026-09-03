from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from db_connection import (
    ConnectionRecord,
    ConnectionRegistry,
    KindSpec,
    StoredConnectionIssue,
    TypeSpec,
    ValidationFailedError,
)
from db_connection.application.public_projection import BrokenPublicConnectionView, ConnectionPublicProjector
from db_connection.domain.drivers import DriverSpec, ODBCDriverOptions


class ProjectedProperties(BaseModel):
    host: str
    password: str


class PublicProperties(BaseModel):
    host: str


class BrokenPublicProperties(BaseModel):
    host: int


class PublicDriverOptions(BaseModel):
    odbc_driver_name: int


def _build_record(
    *,
    properties: dict[str, object],
    driver_options: dict[str, object] | None = None,
    read_issues: list[StoredConnectionIssue] | None = None,
    raw_secrets: object | None = None,
    secrets: dict[str, object] | None = None,
) -> ConnectionRecord:
    now = datetime.now(UTC)
    return ConnectionRecord(
        id="connection-1",
        name="Warehouse",
        kind="sql",
        type="custom-sql",
        driver="pyodbc",
        driver_options=driver_options,
        properties=properties,
        secrets={"password": "secret"} if secrets is None else secrets,
        labels={"env": "test"},
        metadata={"team": "data"},
        extra={"project_id": 42},
        created_at=now,
        updated_at=now,
        read_issues=[] if read_issues is None else read_issues,
        raw_secrets=raw_secrets,
    )


def _build_registry(
    *, public_model: type[BaseModel], public_driver_options_model: type[BaseModel]
) -> ConnectionRegistry:
    registry = ConnectionRegistry()
    registry.register_kind(KindSpec(name="sql"))
    registry.register_type(
        TypeSpec(
            name="custom-sql",
            kind="sql",
            properties_model=ProjectedProperties,
            public_model=public_model,
            driver_specs=[
                DriverSpec(
                    name="pyodbc",
                    options_model=ODBCDriverOptions,
                    public_options_model=public_driver_options_model,
                )
            ],
            default_driver="pyodbc",
        )
    )
    return registry


def test_public_projector_uses_public_model_and_hides_secrets() -> None:
    projector = ConnectionPublicProjector(
        _build_registry(public_model=PublicProperties, public_driver_options_model=ODBCDriverOptions)
    )

    public_view = projector.build(
        _build_record(
            properties={"host": "db.internal", "password": "secret"},
            driver_options={"driver_name": "ODBC Driver 18 for SQL Server"},
        )
    )

    assert isinstance(public_view.properties, PublicProperties)
    assert public_view.properties.model_dump(mode="python") == {"host": "db.internal"}
    assert "password" not in public_view.properties.model_dump(mode="python")
    assert public_view.driver_options is not None
    assert public_view.driver_options.model_dump(mode="python") == {"odbc_driver_name": "ODBC Driver 18 for SQL Server"}
    assert public_view.extra == {"project_id": 42}


def test_public_projector_rejects_invalid_stored_properties() -> None:
    projector = ConnectionPublicProjector(
        _build_registry(public_model=PublicProperties, public_driver_options_model=ODBCDriverOptions)
    )

    with pytest.raises(ValidationFailedError, match="Stored connection payload is invalid."):
        projector.build(_build_record(properties={"password": "secret"}))


def test_public_projector_rejects_invalid_public_driver_options() -> None:
    projector = ConnectionPublicProjector(
        _build_registry(public_model=PublicProperties, public_driver_options_model=PublicDriverOptions)
    )

    with pytest.raises(ValidationFailedError, match="Stored driver options payload is invalid."):
        projector.build(
            _build_record(
                properties={"host": "db.internal", "password": "secret"},
                driver_options={"driver_name": "ODBC Driver 18 for SQL Server"},
            )
        )


def test_public_projector_rejects_invalid_public_properties_model() -> None:
    projector = ConnectionPublicProjector(
        _build_registry(public_model=BrokenPublicProperties, public_driver_options_model=ODBCDriverOptions)
    )

    with pytest.raises(ValidationFailedError, match="Stored connection payload is invalid."):
        projector.build(
            _build_record(
                properties={"host": "db.internal", "password": "secret"},
                driver_options={"driver_name": "ODBC Driver 18 for SQL Server"},
            )
        )


def test_public_projector_build_any_returns_broken_view_for_invalid_properties() -> None:
    projector = ConnectionPublicProjector(
        _build_registry(public_model=PublicProperties, public_driver_options_model=ODBCDriverOptions)
    )

    public_view = projector.build_any(
        _build_record(
            properties={"server": "db.internal"},
            driver_options={"driver_name": "ODBC Driver 18 for SQL Server"},
        )
    )

    assert isinstance(public_view, BrokenPublicConnectionView)
    assert public_view.state == "invalid"
    assert public_view.raw_properties == {"server": "db.internal"}
    assert [issue.code for issue in public_view.issues] == ["invalid_properties"]


def test_public_projector_build_any_preserves_raw_secrets_for_invalid_decrypted_payload() -> None:
    projector = ConnectionPublicProjector(
        _build_registry(public_model=PublicProperties, public_driver_options_model=ODBCDriverOptions)
    )

    public_view = projector.build_any(
        _build_record(
            properties={"host": "db.internal", "password": "secret"},
            driver_options={"driver_name": "ODBC Driver 18 for SQL Server"},
            read_issues=[
                StoredConnectionIssue(
                    field="secrets",
                    code="invalid_secrets",
                    message="Stored connection secrets payload is invalid.",
                )
            ],
            raw_secrets=["broken", "json"],
            secrets={},
        )
    )

    assert isinstance(public_view, BrokenPublicConnectionView)
    assert public_view.raw_secrets == ["broken", "json"]
    assert [issue.code for issue in public_view.issues] == ["invalid_secrets"]
