from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from db_connection import (
    AccessContext,
    AccessDeniedError,
    APISchemaSet,
    ConnectionDraft,
    ConnectionListQuery,
    ConnectionRecord,
    ConnectionRepository,
    ConnectionUnitOfWork,
    ConnectionUnitOfWorkFactory,
    DBConnectionExtension,
    EncryptionProvider,
    FernetEncryptionProvider,
    NoOpEncryptionProvider,
    StoredConnectionRecordMapper,
)
from db_connection.connectors.s3 import S3Connector


def _get_parameter_schema(openapi: dict, *, path: str, method: str, parameter_name: str) -> dict:
    parameters = openapi["paths"][path][method]["parameters"]
    return next(parameter["schema"] for parameter in parameters if parameter["name"] == parameter_name)


class ProjectStoredConnection(SQLModel, table=True):
    __tablename__ = "project_db_connections"

    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    kind: str = Field(index=True)
    type: str = Field(index=True)
    driver: str | None = Field(default=None)
    project_id: int = Field(index=True)
    owner_id: str = Field(index=True)
    properties_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    secrets_ciphertext: str = Field(default="{}")
    labels_json: dict[str, str] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = Field(default=None)


class ProjectConnectionCreate(BaseModel):
    name: str
    kind: str
    type: str
    project_id: int
    owner_id: str
    properties: dict[str, Any]
    secrets: dict[str, Any] = {}
    labels: dict[str, str] = {}
    metadata: dict[str, Any] = {}


class ProjectConnectionUpdate(BaseModel):
    name: str | None = None
    project_id: int | None = None
    owner_id: str | None = None
    properties: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    labels: dict[str, str] | None = None
    metadata: dict[str, Any] | None = None


class ProjectConnectionRead(BaseModel):
    id: str
    name: str
    kind: str
    type: str
    project_id: int
    owner_id: str
    properties: dict[str, Any]
    labels: dict[str, str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class ProjectConnectionRepository(ConnectionRepository):
    def __init__(self, session: Session, *, encryption_provider: EncryptionProvider) -> None:
        self._session = session
        self._encryption_provider = encryption_provider
        self._record_mapper = StoredConnectionRecordMapper(encryption_provider=encryption_provider)

    def create(self, draft: ConnectionDraft) -> ConnectionRecord:
        now = datetime.now(UTC)
        row = ProjectStoredConnection(
            id=str(uuid4()),
            name=draft.name,
            kind=draft.kind,
            type=draft.type,
            driver=draft.driver,
            project_id=int(draft.extra["project_id"]),
            owner_id=str(draft.extra["owner_id"]),
            properties_json=draft.properties,
            secrets_ciphertext=self._encryption_provider.encrypt(draft.secrets),
            labels_json=draft.labels,
            metadata_json=draft.metadata,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_record(row)

    def list(self, query: ConnectionListQuery) -> list[ConnectionRecord]:
        statement = select(ProjectStoredConnection).where(ProjectStoredConnection.deleted_at.is_(None))
        owner_id = query.extra_filters.get("owner_id")
        if owner_id is not None:
            statement = statement.where(ProjectStoredConnection.owner_id == owner_id)
        rows = self._session.exec(statement).all()
        return [self._to_record(row) for row in rows]

    def get(self, connection_id: str) -> ConnectionRecord | None:
        row = self._session.get(ProjectStoredConnection, connection_id)
        return None if row is None else self._to_record(row)

    def replace(self, connection_id: str, draft: ConnectionDraft) -> ConnectionRecord | None:
        row = self._session.get(ProjectStoredConnection, connection_id)
        if row is None:
            return None
        row.name = draft.name
        row.project_id = int(draft.extra["project_id"])
        row.owner_id = str(draft.extra["owner_id"])
        row.properties_json = draft.properties
        row.secrets_ciphertext = self._encryption_provider.encrypt(draft.secrets)
        row.labels_json = draft.labels
        row.metadata_json = draft.metadata
        row.updated_at = datetime.now(UTC)
        self._session.add(row)
        self._session.flush()
        return self._to_record(row)

    def delete(self, connection_id: str) -> ConnectionRecord | None:
        row = self._session.get(ProjectStoredConnection, connection_id)
        if row is None:
            return None
        row.deleted_at = datetime.now(UTC)
        row.updated_at = row.deleted_at
        self._session.add(row)
        self._session.flush()
        return self._to_record(row)

    def _to_record(self, row: ProjectStoredConnection) -> ConnectionRecord:
        return self._record_mapper.to_record(
            id=row.id,
            name=row.name,
            kind=row.kind,
            type=row.type,
            driver=row.driver,
            properties_json=row.properties_json,
            secrets_ciphertext=row.secrets_ciphertext,
            labels_json=row.labels_json,
            metadata_json=row.metadata_json,
            extra={"project_id": row.project_id, "owner_id": row.owner_id},
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )


class OwnerScopedPolicy:
    def scope_list(self, ctx: AccessContext, query: ConnectionListQuery) -> ConnectionListQuery:
        return query.model_copy(update={"extra_filters": {"owner_id": ctx.actor["owner_id"]}})

    def can_create(self, ctx: AccessContext) -> None:
        if ctx.payload is None:
            return
        if ctx.payload.get("owner_id") != ctx.actor["owner_id"]:
            raise AccessDeniedError("Cannot create a connection for another owner.")

    def can_get_one(self, ctx: AccessContext, connection: ConnectionRecord) -> None:
        if connection.extra["owner_id"] != ctx.actor["owner_id"]:
            raise AccessDeniedError("Connection belongs to a different owner.")

    def can_update(self, ctx: AccessContext, connection: ConnectionRecord, patch: dict[str, Any]) -> None:
        if connection.extra["owner_id"] != ctx.actor["owner_id"]:
            raise AccessDeniedError("Connection belongs to a different owner.")

    def can_delete(self, ctx: AccessContext, connection: ConnectionRecord) -> None:
        if connection.extra["owner_id"] != ctx.actor["owner_id"]:
            raise AccessDeniedError("Connection belongs to a different owner.")


def get_actor(x_owner_id: str = Header(...)) -> dict[str, str]:
    return {"owner_id": x_owner_id}


class SyncProjectUnitOfWork(ConnectionUnitOfWork):
    def __init__(self, engine, *, encryption_provider: EncryptionProvider) -> None:
        self._engine = engine
        self._encryption_provider = encryption_provider
        self._session: Session | None = None
        self._connections: ProjectConnectionRepository | None = None

    @property
    def connections(self) -> ProjectConnectionRepository:
        if self._connections is None:
            raise RuntimeError("Unit of work has not been entered.")
        return self._connections

    async def __aenter__(self) -> SyncProjectUnitOfWork:
        self._session = Session(self._engine)
        self._connections = ProjectConnectionRepository(
            self._session,
            encryption_provider=self._encryption_provider,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc is not None and self._session is not None:
                self._session.rollback()
        finally:
            if self._session is not None:
                self._session.close()
            self._connections = None
            self._session = None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        self._session.rollback()


class SyncProjectUnitOfWorkFactory(ConnectionUnitOfWorkFactory):
    def __init__(self, engine, *, encryption_provider: EncryptionProvider) -> None:
        self._engine = engine
        self._encryption_provider = encryption_provider

    def __call__(self) -> SyncProjectUnitOfWork:
        return SyncProjectUnitOfWork(
            self._engine,
            encryption_provider=self._encryption_provider,
        )


def build_custom_app(
    *,
    encryption_provider: EncryptionProvider | None = None,
) -> tuple[FastAPI, Any]:
    resolved_encryption_provider = encryption_provider or NoOpEncryptionProvider()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    extension = DBConnectionExtension(
        uow_factory=SyncProjectUnitOfWorkFactory(
            engine,
            encryption_provider=resolved_encryption_provider,
        ),
        access_policy=OwnerScopedPolicy(),
        api_schemas=APISchemaSet(
            create=ProjectConnectionCreate,
            read=ProjectConnectionRead,
            update=ProjectConnectionUpdate,
        ),
        get_actor=get_actor,
    )
    extension.install(app)
    return app, engine


def build_custom_client() -> Generator[TestClient, None, None]:
    app, _ = build_custom_app()
    with TestClient(app) as client:
        yield client


def build_s3_project_payload(*, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "file",
        "type": "s3",
        "project_id": 42,
        "owner_id": "owner-1",
        "properties": {
            "bucket": "test-bucket",
            "region_name": None,
            "endpoint_url": "http://127.0.0.1:3900",
            "use_ssl": True,
            "path_style": False,
            "signature_version": None,
            "prefix": None,
        },
        "secrets": {
            "access_token_id": "minioadmin",
            "access_token_key": "minioadmin",
            "session_token": None,
        },
        "labels": {},
        "metadata": {},
    }


def test_custom_repository_fields_are_exposed_in_api_and_openapi() -> None:
    client = next(build_custom_client())
    try:
        response = client.post(
            "/db-connections",
            headers={"x-owner-id": "owner-1"},
            json={
                "name": "Warehouse",
                "kind": "sql",
                "type": "postgres",
                "project_id": 42,
                "owner_id": "owner-1",
                "properties": {
                    "host": "localhost",
                    "port": 5432,
                    "username": "service_user",
                    "database": "warehouse",
                    "secure": False,
                },
                "secrets": {"password": "secret"},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == 42
        assert payload["owner_id"] == "owner-1"

        list_response = client.get("/db-connections", headers={"x-owner-id": "owner-1"})
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        foreign_get = client.get(
            f"/db-connections/{payload['id']}",
            headers={"x-owner-id": "owner-2"},
        )
        assert foreign_get.status_code == 403

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        schemas = openapi.json()["components"]["schemas"]
        create_schema = schemas["ProjectConnectionCreate"]
        read_schema = schemas["ProjectConnectionRead"]
        assert "project_id" in create_schema["properties"]
        assert "owner_id" in create_schema["properties"]
        assert "project_id" in read_schema["properties"]
        assert "owner_id" in read_schema["properties"]

        openapi_payload = openapi.json()
        kind_schema = _get_parameter_schema(
            openapi_payload,
            path="/db-connections",
            method="get",
            parameter_name="kind",
        )
        type_schema = _get_parameter_schema(
            openapi_payload,
            path="/db-connections",
            method="get",
            parameter_name="type",
        )
        assert {"enum": ["file", "queue", "sql"], "type": "string"} in kind_schema["anyOf"]
        assert {"type": "string"} in kind_schema["anyOf"]
        assert {"type": "string"} in type_schema["anyOf"]
        assert any("postgres" in entry["enum"] for entry in type_schema["anyOf"] if "enum" in entry)
    finally:
        client.close()


def test_custom_repository_mapper_returns_broken_rows_for_unreadable_secrets() -> None:
    encryption_provider = FernetEncryptionProvider(Fernet.generate_key())
    app, engine = build_custom_app(encryption_provider=encryption_provider)

    with TestClient(app) as client:
        healthy_response = client.post(
            "/db-connections",
            headers={"x-owner-id": "owner-1"},
            json={
                "name": "Healthy",
                "kind": "sql",
                "type": "postgres",
                "project_id": 42,
                "owner_id": "owner-1",
                "properties": {
                    "host": "localhost",
                    "port": 5432,
                    "username": "service_user",
                    "database": "warehouse",
                    "secure": False,
                },
                "secrets": {"password": "secret"},
            },
        )
        broken_response = client.post(
            "/db-connections",
            headers={"x-owner-id": "owner-1"},
            json={
                "name": "Broken",
                "kind": "sql",
                "type": "postgres",
                "project_id": 42,
                "owner_id": "owner-1",
                "properties": {
                    "host": "localhost",
                    "port": 5432,
                    "username": "service_user",
                    "database": "warehouse",
                    "secure": False,
                },
                "secrets": {"password": "secret"},
            },
        )

        assert healthy_response.status_code == 200
        assert broken_response.status_code == 200

        broken_id = broken_response.json()["id"]
        wrong_key_provider = FernetEncryptionProvider(Fernet.generate_key())
        with Session(engine) as session:
            row = session.get(ProjectStoredConnection, broken_id)
            assert row is not None
            row.secrets_ciphertext = wrong_key_provider.encrypt({"password": "wrong-key-secret"})
            session.add(row)
            session.commit()

        list_response = client.get("/db-connections", headers={"x-owner-id": "owner-1"})
        assert list_response.status_code == 200
        payload = {item["name"]: item for item in list_response.json()}
        assert "state" not in payload["Healthy"]
        assert payload["Broken"]["state"] == "invalid"
        assert [issue["code"] for issue in payload["Broken"]["issues"]] == ["unreadable_secrets"]
        assert payload["Broken"].get("raw_secrets") is None

        get_response = client.get(f"/db-connections/{broken_id}", headers={"x-owner-id": "owner-1"})
        assert get_response.status_code == 200
        assert get_response.json()["state"] == "invalid"
        assert [issue["code"] for issue in get_response.json()["issues"]] == ["unreadable_secrets"]


def test_check_payload_logs_traceback_for_connector_failures(monkeypatch, caplog) -> None:
    def fail_get_client(self, connection) -> object:
        raise RuntimeError("s3 probe failed")

    monkeypatch.setattr(S3Connector, "_get_client_blocking", fail_get_client)

    client = next(build_custom_client())
    try:
        with caplog.at_level("ERROR", logger="db_connection.connectors"):
            response = client.post(
                "/db-connections/check",
                headers={"x-owner-id": "owner-1"},
                json=build_s3_project_payload(name="Payload check"),
            )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is False
    assert payload["exception"] == "s3 probe failed"
    assert any("S3Connector" in record.getMessage() for record in caplog.records)
    assert any("Payload check" in record.getMessage() for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)


def test_check_stored_logs_traceback_for_connector_failures(monkeypatch, caplog) -> None:
    def fail_get_client(self, connection) -> object:
        raise RuntimeError("stored s3 probe failed")

    monkeypatch.setattr(S3Connector, "_get_client_blocking", fail_get_client)

    client = next(build_custom_client())
    try:
        create_response = client.post(
            "/db-connections",
            headers={"x-owner-id": "owner-1"},
            json=build_s3_project_payload(name="Stored check"),
        )
        assert create_response.status_code == 200
        connection_id = create_response.json()["id"]

        with caplog.at_level("ERROR", logger="db_connection.connectors"):
            response = client.post(
                f"/db-connections/{connection_id}/check",
                headers={"x-owner-id": "owner-1"},
                json={},
            )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is False
    assert payload["exception"] == "stored s3 probe failed"
    assert any("S3Connector" in record.getMessage() for record in caplog.records)
    assert any("Stored check" in record.getMessage() for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)
