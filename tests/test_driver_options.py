from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from db_connection import ConnectionDraft, ConnectionRecord, DefaultSQLModelConnectionUnitOfWorkFactory
from db_connection.application.public_projection import ConnectionPublicProjector
from db_connection.application.validation import ValidationService
from db_connection.connectors.sql import SQLConnector
from db_connection.domain.drivers import ODBCDriverOptions
from db_connection.errors import ValidationFailedError
from db_connection.registry.defaults import build_default_registry


def test_validation_requires_mssql_driver_options_for_sync_and_async_drivers() -> None:
    validation = ValidationService(build_default_registry())

    for driver_name in ("pyodbc", "aioodbc"):
        with pytest.raises(ValidationFailedError):
            validation.validate(
                ConnectionDraft(
                    name=f"mssql-{driver_name}",
                    kind="sql",
                    type="mssql",
                    driver=driver_name,
                    properties={
                        "host": "localhost",
                        "port": 1433,
                        "username": "svc",
                        "database": "warehouse",
                    },
                    secrets={"password": "secret"},
                )
            )


@pytest.mark.parametrize("connection_type,driver", [("postgres", "psycopg"), ("mysql", "pymysql"), ("clickhouse", "native"), ("oracle", "oracledb")])
def test_validation_rejects_driver_options_for_no_options_drivers(connection_type: str, driver: str) -> None:
    validation = ValidationService(build_default_registry())

    with pytest.raises(ValidationFailedError):
        validation.validate(
            ConnectionDraft(
                name=f"{connection_type}-with-driver-options",
                kind="sql",
                type=connection_type,
                driver=driver,
                driver_options={"unexpected": "value"},
                properties={
                    "host": "localhost",
                    "port": 5432 if connection_type == "postgres" else 3306,
                    "username": "svc",
                    "database": "warehouse",
                },
                secrets={"password": "secret"},
            )
        )


def test_sync_mssql_url_uses_top_level_driver_and_typed_odbc_driver_name() -> None:
    connection = ValidationService(build_default_registry()).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="mssql",
            driver="pyodbc",
            driver_options=ODBCDriverOptions(odbc_driver_name="ODBC Driver 18 for SQL Server"),
            properties={
                "host": "localhost",
                "port": 1433,
                "username": "svc",
                "database": "warehouse",
                "secure": True,
            },
            secrets={"password": "secret"},
        )
    )

    url = SQLConnector(preferred_mode="sync").build_connection_url(connection)

    assert url.drivername == "mssql+pyodbc"
    assert url.host == "localhost"
    assert url.port == 1433
    assert url.query["driver"] == "ODBC Driver 18 for SQL Server"


def test_async_mssql_url_uses_top_level_driver_and_typed_odbc_driver_name() -> None:
    connection = ValidationService(build_default_registry()).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="mssql",
            driver="aioodbc",
            driver_options=ODBCDriverOptions(odbc_driver_name="ODBC Driver 18 for SQL Server"),
            properties={
                "host": "localhost",
                "port": 1433,
                "username": "svc",
                "database": "warehouse",
                "secure": True,
            },
            secrets={"password": "secret"},
        )
    )

    url = SQLConnector(preferred_mode="async").build_connection_url(connection)

    assert url.drivername == "mssql+aioodbc"
    assert url.host == "localhost"
    assert url.port == 1433
    assert url.query["driver"] == "ODBC Driver 18 for SQL Server"


def test_sync_mssql_named_instance_url_uses_instance_host_without_port() -> None:
    connection = ValidationService(build_default_registry()).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="mssql",
            driver="pyodbc",
            driver_options=ODBCDriverOptions(odbc_driver_name="ODBC Driver 18 for SQL Server"),
            properties={
                "host": "192.168.1.10",
                "instance_name": "CLIENT_A",
                "username": "svc",
                "database": "warehouse",
                "secure": True,
            },
            secrets={"password": "secret"},
        )
    )

    url = SQLConnector(preferred_mode="sync").build_connection_url(connection)

    assert url.drivername == "mssql+pyodbc"
    assert url.host == r"192.168.1.10\CLIENT_A"
    assert url.port is None
    assert url.query["driver"] == "ODBC Driver 18 for SQL Server"


def test_async_mssql_named_instance_url_uses_instance_host_without_port() -> None:
    connection = ValidationService(build_default_registry()).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="mssql",
            driver="aioodbc",
            driver_options=ODBCDriverOptions(odbc_driver_name="ODBC Driver 18 for SQL Server"),
            properties={
                "host": "192.168.1.10",
                "instance_name": "CLIENT_A",
                "username": "svc",
                "database": "warehouse",
                "secure": True,
            },
            secrets={"password": "secret"},
        )
    )

    url = SQLConnector(preferred_mode="async").build_connection_url(connection)

    assert url.drivername == "mssql+aioodbc"
    assert url.host == r"192.168.1.10\CLIENT_A"
    assert url.port is None
    assert url.query["driver"] == "ODBC Driver 18 for SQL Server"


def test_validation_rejects_mssql_payload_with_port_and_instance_name() -> None:
    validation = ValidationService(build_default_registry())

    with pytest.raises(ValidationFailedError) as exc_info:
        validation.validate(
            ConnectionDraft(
                name="warehouse",
                kind="sql",
                type="mssql",
                driver="pyodbc",
                driver_options=ODBCDriverOptions(odbc_driver_name="ODBC Driver 18 for SQL Server"),
                properties={
                    "host": "192.168.1.10",
                    "port": 1433,
                    "instance_name": "CLIENT_A",
                    "username": "svc",
                    "database": "warehouse",
                },
                secrets={"password": "secret"},
            )
        )

    assert exc_info.value.details["errors"]


def test_mssql_named_instance_public_projection_round_trips_properties() -> None:
    registry = build_default_registry()
    validated = ValidationService(registry).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="mssql",
            driver="pyodbc",
            driver_options=ODBCDriverOptions(odbc_driver_name="ODBC Driver 18 for SQL Server"),
            properties={
                "host": "192.168.1.10",
                "instance_name": "CLIENT_A",
                "username": "svc",
                "database": "warehouse",
            },
            secrets={"password": "secret"},
        )
    )
    record = ConnectionRecord(
        id="mssql-named",
        name="warehouse",
        kind="sql",
        type="mssql",
        driver="pyodbc",
        driver_options=validated.driver_options,
        properties=validated.properties.model_dump(mode="json"),
        secrets={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    public_view = ConnectionPublicProjector(registry).build(record)

    assert public_view.properties.model_dump(mode="python")["instance_name"] == "CLIENT_A"


def test_default_postgres_url_uses_psycopg_async_path() -> None:
    connection = ValidationService(build_default_registry()).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="postgres",
            properties={
                "host": "localhost",
                "port": 5432,
                "username": "svc",
                "database": "warehouse",
            },
            secrets={"password": "secret"},
        )
    )

    url = SQLConnector().build_connection_url(connection)

    assert connection.driver == "psycopg"
    assert url.drivername == "postgresql+psycopg"


def test_async_preferred_connector_falls_back_to_sync_engine_for_sync_only_driver(monkeypatch) -> None:
    connection = ValidationService(build_default_registry()).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="mysql",
            driver="pymysql",
            properties={
                "host": "localhost",
                "port": 3306,
                "username": "svc",
                "database": "warehouse",
            },
            secrets={"password": "secret"},
        )
    )

    sync_engine = object()
    async_called = False

    def fake_create_engine(url) -> object:
        assert url.drivername == "mysql+pymysql"
        return sync_engine

    def fake_create_async_engine(url) -> object:
        nonlocal async_called
        async_called = True
        raise AssertionError("async engine path must not be used for sync-only drivers")

    monkeypatch.setattr("db_connection.connectors.sql.create_engine", fake_create_engine)
    monkeypatch.setattr("db_connection.connectors.sql.create_async_engine", fake_create_async_engine)

    client = asyncio.run(SQLConnector().get_client(connection))

    assert client is sync_engine
    assert async_called is False


def test_async_preferred_connector_returns_async_engine_for_psycopg(monkeypatch) -> None:
    connection = ValidationService(build_default_registry()).validate(
        ConnectionDraft(
            name="warehouse",
            kind="sql",
            type="postgres",
            driver="psycopg",
            properties={
                "host": "localhost",
                "port": 5432,
                "username": "svc",
                "database": "warehouse",
            },
            secrets={"password": "secret"},
        )
    )

    async_engine = object()
    sync_called = False

    def fake_create_engine(url) -> object:
        nonlocal sync_called
        sync_called = True
        raise AssertionError("sync engine path must not be used for psycopg async mode")

    def fake_create_async_engine(url) -> object:
        assert url.drivername == "postgresql+psycopg"
        return async_engine

    monkeypatch.setattr("db_connection.connectors.sql.create_engine", fake_create_engine)
    monkeypatch.setattr("db_connection.connectors.sql.create_async_engine", fake_create_async_engine)

    client = asyncio.run(SQLConnector().get_client(connection))

    assert client is async_engine
    assert sync_called is False


def test_default_repository_round_trips_typed_driver_options(stored_connection_model) -> None:
    async def run_round_trip():
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        uow_factory = DefaultSQLModelConnectionUnitOfWorkFactory(
            session_factory,
            model_class=stored_connection_model,
        )

        async with uow_factory() as uow:
            created = await uow.connections.create(
                ConnectionDraft(
                    name="warehouse",
                    kind="sql",
                    type="mssql",
                    driver="pyodbc",
                    driver_options=ODBCDriverOptions(odbc_driver_name="ODBC Driver 18 for SQL Server"),
                    properties={"host": "localhost"},
                    secrets={"password": "secret"},
                )
            )
            await uow.commit()

        async with uow_factory() as uow:
            loaded = await uow.connections.get(created.id)

        await engine.dispose()
        return loaded

    loaded = asyncio.run(run_round_trip())

    assert loaded is not None
    assert isinstance(loaded.driver_options, ODBCDriverOptions)
    assert loaded.driver_options.odbc_driver_name == "ODBC Driver 18 for SQL Server"
