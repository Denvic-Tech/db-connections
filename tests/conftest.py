from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from db_connection import (
    DBConnectionExtension,
    DefaultSQLModelConnectionUnitOfWorkFactory,
    DefaultStoredConnection,
)


class StoredConnectionTable(DefaultStoredConnection, table=True):
    __tablename__ = "db_connections"


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)


@pytest.fixture
def postgres_payload() -> dict:
    return {
        "name": "Primary Postgres",
        "kind": "sql",
        "type": "postgres",
        "properties": {
            "host": "localhost",
            "port": 5432,
            "username": "service_user",
            "database": "analytics",
            "secure": False,
        },
        "secrets": {
            "password": "super-secret",
        },
        "labels": {
            "env": "test",
        },
        "metadata": {
            "team": "data-platform",
        },
    }


@pytest.fixture
def mssql_payload() -> dict:
    return {
        "name": "Primary MSSQL",
        "kind": "sql",
        "type": "mssql",
        "properties": {
            "host": "localhost",
            "port": 1433,
            "username": "service_user",
            "database": "analytics",
            "secure": True,
        },
        "driver_options": {
            "driver_name": "ODBC Driver 18 for SQL Server",
        },
        "secrets": {
            "password": "super-secret",
        },
        "labels": {
            "env": "test",
        },
        "metadata": {
            "team": "data-platform",
        },
    }


@pytest.fixture
def engine() -> Generator[AsyncEngine, None, None]:
    db_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_create_schema(db_engine))
    try:
        yield db_engine
    finally:
        asyncio.run(db_engine.dispose())


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
def stored_connection_model() -> type[StoredConnectionTable]:
    return StoredConnectionTable


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> DefaultSQLModelConnectionUnitOfWorkFactory:
    return DefaultSQLModelConnectionUnitOfWorkFactory(
        session_factory,
        model_class=StoredConnectionTable,
    )


@pytest.fixture
def extension(uow_factory: DefaultSQLModelConnectionUnitOfWorkFactory) -> DBConnectionExtension:
    return DBConnectionExtension(uow_factory=uow_factory)


@pytest.fixture
def app(extension: DBConnectionExtension) -> FastAPI:
    application = FastAPI()
    extension.install(application)
    return application


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
