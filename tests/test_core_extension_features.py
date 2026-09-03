from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import APIRouter, FastAPI, Header
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from db_connection import (
    ConnectionCheckResult,
    ConnectionListQuery,
    ConnectionRegistry,
    Connector,
    DBConnectionExtension,
    DefaultSQLModelConnectionUnitOfWorkFactory,
    DefaultStoredConnection,
    KindSpec,
    TypeSpec,
    ValidationFailedError,
    load_dsl_data,
)
from tests.conftest import StoredConnectionTable


class BuilderDSLProperties(BaseModel):
    value: str


class BuilderDSLConnector(Connector):
    def check(self, connection) -> ConnectionCheckResult:
        return ConnectionCheckResult(
            name=connection.name,
            connected=True,
            message=connection.properties.value,
        )

    def get_client(self, connection) -> str:
        return connection.properties.value


def bootstrap_test_plugin(registry: ConnectionRegistry) -> None:
    registry.register_kind(KindSpec(name="plugin"))
    registry.register_type(
        TypeSpec(
            name="pluginfake",
            kind="plugin",
            properties_model=BuilderDSLProperties,
            public_model=BuilderDSLProperties,
            connector_factory=BuilderDSLConnector,
        )
    )


def build_uow_factory() -> DefaultSQLModelConnectionUnitOfWorkFactory:
    async def create_schema(engine) -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(create_schema(engine))
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return DefaultSQLModelConnectionUnitOfWorkFactory(
        session_factory,
        model_class=StoredConnectionTable,
    )


def test_default_uow_factory_requires_table_model() -> None:
    with pytest.raises(TypeError, match="table=True"):
        DefaultSQLModelConnectionUnitOfWorkFactory(
            object(),  # type: ignore[arg-type]
            model_class=DefaultStoredConnection,
        )


def build_postgres_payload(
    *,
    name: str,
    env: str = "test",
    team: str = "data-platform",
    project_id: int = 1,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "sql",
        "type": "postgres",
        "properties": {
            "host": "localhost",
            "port": 5432,
            "username": "service_user",
            "database": "analytics",
            "secure": False,
        },
        "secrets": {"password": "super-secret"},
        "labels": {"env": env},
        "metadata": {"team": team},
        "project_id": project_id,
    }


class FakeEntryPoint:
    def __init__(self, name: str, group: str, loader) -> None:
        self.name = name
        self.group = group
        self._loader = loader

    def load(self):
        return self._loader


class FakeEntryPoints(list[FakeEntryPoint]):
    def select(self, *, group: str):
        return [entry for entry in self if entry.group == group]


def _get_parameter_schema(openapi: dict, *, path: str, method: str, parameter_name: str) -> dict:
    parameters = openapi["paths"][path][method]["parameters"]
    return next(parameter["schema"] for parameter in parameters if parameter["name"] == parameter_name)


def test_builder_supports_crud_and_runtime_settings_update() -> None:
    extension = (
        DBConnectionExtension.builder()
        .with_uow_factory(build_uow_factory())
        .with_max_connections(1)
        .build()
    )
    app = FastAPI()
    extension.install(app)

    with TestClient(app) as client:
        first = client.post("/db-connections", json=build_postgres_payload(name="Primary"))
        assert first.status_code == 200

        limited = client.post("/db-connections", json=build_postgres_payload(name="Secondary"))
        assert limited.status_code == 409

        updated_settings = extension.update_settings(max_connections=2)
        assert updated_settings.max_connections == 2

        second = client.post("/db-connections", json=build_postgres_payload(name="Secondary"))
        assert second.status_code == 200


def test_http_list_supports_labels_metadata_and_extra_filters() -> None:
    extension = DBConnectionExtension.builder().with_uow_factory(build_uow_factory()).build()
    app = FastAPI()
    extension.install(app)

    with TestClient(app) as client:
        client.post(
            "/db-connections",
            json=build_postgres_payload(name="Prod", env="prod", team="core", project_id=10),
        )
        client.post(
            "/db-connections",
            json=build_postgres_payload(name="Dev", env="dev", team="labs", project_id=20),
        )

        by_label = client.get("/db-connections", params={"labels": json.dumps({"env": "prod"})})
        assert by_label.status_code == 200
        assert [item["name"] for item in by_label.json()] == ["Prod"]

        by_metadata = client.get(
            "/db-connections",
            params={"metadata": json.dumps({"team": "labs"})},
        )
        assert by_metadata.status_code == 200
        assert [item["name"] for item in by_metadata.json()] == ["Dev"]

        by_extra = client.get("/db-connections", params={"extra": json.dumps({"project_id": 10})})
        assert by_extra.status_code == 200
        assert [item["name"] for item in by_extra.json()] == ["Prod"]

        invalid = client.get("/db-connections", params={"labels": "[]"})
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "validation_failed"


def test_extension_uses_request_scoped_uow_dependency_without_internal_commit() -> None:
    uow_factory = build_uow_factory()
    commit_calls: list[str] = []

    async def get_uow():
        async with uow_factory() as uow:
            original_commit = uow.commit

            async def tracked_commit() -> None:
                commit_calls.append("commit")
                await original_commit()

            uow.commit = tracked_commit  # type: ignore[method-assign]
            yield uow
            await uow.commit()

    extension = (
        DBConnectionExtension.builder()
        .with_uow_factory(uow_factory)
        .with_uow_dependency(get_uow)
        .build()
    )
    app = FastAPI()
    extension.install(app)

    with TestClient(app) as client:
        create_response = client.post("/db-connections", json=build_postgres_payload(name="Scoped"))
        assert create_response.status_code == 200

    assert commit_calls == ["commit"]

    async def list_records() -> list[str]:
        async with uow_factory() as uow:
            records = await uow.connections.list(ConnectionListQuery())
            return [record.name for record in records]

    assert asyncio.run(list_records()) == ["Scoped"]


def test_extension_can_install_into_api_router() -> None:
    extension = DBConnectionExtension.builder().with_uow_factory(build_uow_factory()).build()
    app = FastAPI()
    parent_router = APIRouter(prefix="/internal")

    extension.install(parent_router)
    app.include_router(parent_router)

    with TestClient(app) as client:
        create_response = client.post("/internal/db-connections", json=build_postgres_payload(name="Nested"))
        assert create_response.status_code == 200

        openapi_response = client.get("/openapi.json")
        assert openapi_response.status_code == 200
        assert "/internal/db-connections" in openapi_response.json()["paths"]


def test_install_can_override_actor_dependency_per_route_set() -> None:
    resolver = HeaderOwnershipResolver()

    def get_internal_actor(x_internal_owner_id: str = Header(...)) -> dict[str, str]:
        return {"owner_id": f"internal:{x_internal_owner_id}"}

    def get_external_actor(x_external_owner_id: str = Header(...)) -> dict[str, str]:
        return {"owner_id": f"external:{x_external_owner_id}"}

    extension = (
        DBConnectionExtension.builder()
        .with_uow_factory(build_uow_factory())
        .with_ownership_resolver(resolver)
        .build()
    )
    app = FastAPI()

    extension.install(app, prefix="/internal-db-connections", get_actor=get_internal_actor)
    extension.install(app, prefix="/external-db-connections", get_actor=get_external_actor)

    with TestClient(app) as client:
        internal_response = client.post(
            "/internal-db-connections/check",
            headers={"x-internal-owner-id": "alice"},
            json=build_postgres_payload(name="Internal"),
        )
        external_response = client.post(
            "/external-db-connections/check",
            headers={"x-external-owner-id": "bob"},
            json=build_postgres_payload(name="External"),
        )

    assert internal_response.status_code == 200
    assert external_response.status_code == 200
    assert resolver.calls == [
        ("check_payload", {"owner_id": "internal:alice"}),
        ("check_payload", {"owner_id": "external:bob"}),
    ]


def test_install_can_override_uow_dependency_per_route_set() -> None:
    default_factory = build_uow_factory()
    override_factory = build_uow_factory()
    default_commits: list[str] = []
    override_commits: list[str] = []

    async def get_default_uow():
        async with default_factory() as uow:
            original_commit = uow.commit

            async def tracked_commit() -> None:
                default_commits.append("commit")
                await original_commit()

            uow.commit = tracked_commit  # type: ignore[method-assign]
            yield uow
            await uow.commit()

    async def get_override_uow():
        async with override_factory() as uow:
            original_commit = uow.commit

            async def tracked_commit() -> None:
                override_commits.append("commit")
                await original_commit()

            uow.commit = tracked_commit  # type: ignore[method-assign]
            yield uow
            await uow.commit()

    extension = (
        DBConnectionExtension.builder()
        .with_uow_factory(default_factory)
        .with_uow_dependency(get_default_uow)
        .build()
    )
    app = FastAPI()

    extension.install(app, prefix="/default-db-connections")
    extension.install(app, prefix="/override-db-connections", get_uow=get_override_uow)

    with TestClient(app) as client:
        default_response = client.post(
            "/default-db-connections",
            json=build_postgres_payload(name="Default"),
        )
        override_response = client.post(
            "/override-db-connections",
            json=build_postgres_payload(name="Override"),
        )

    assert default_response.status_code == 200
    assert override_response.status_code == 200
    assert default_commits == ["commit"]
    assert override_commits == ["commit"]

    async def list_records(factory: DefaultSQLModelConnectionUnitOfWorkFactory) -> list[str]:
        async with factory() as uow:
            records = await uow.connections.list(ConnectionListQuery())
            return [record.name for record in records]

    assert asyncio.run(list_records(default_factory)) == ["Default"]
    assert asyncio.run(list_records(override_factory)) == ["Override"]


def test_dsl_loading_supports_data_json_and_yaml() -> None:
    dsl_payload = {
        "settings": {"max_connections": 3},
        "registry": {
            "kinds": [{"name": "customdsl", "capabilities": ["check"]}],
            "types": [
                {
                    "name": "dslfake",
                    "kind": "customdsl",
                    "properties_model": f"{__name__}.BuilderDSLProperties",
                    "public_model": f"{__name__}.BuilderDSLProperties",
                    "connector_factory": f"{__name__}.BuilderDSLConnector",
                }
            ],
        },
    }

    config = load_dsl_data(dsl_payload)
    assert config.settings.max_connections == 3
    assert config.registry.types[0].name == "dslfake"

    artifacts_dir = Path("tmp") / "test-core-extension-features"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    json_path = artifacts_dir / "db-connection.json"
    yaml_path = artifacts_dir / "db-connection.yaml"
    json_path.write_text(json.dumps(dsl_payload), encoding="utf-8")
    yaml_path.write_text(yaml.safe_dump(dsl_payload), encoding="utf-8")

    try:
        json_extension = (
            DBConnectionExtension.builder()
            .with_uow_factory(build_uow_factory())
            .with_default_types(False)
            .with_dsl_file(json_path)
            .build()
        )
        yaml_extension = (
            DBConnectionExtension.builder()
            .with_uow_factory(build_uow_factory())
            .with_default_types(False)
            .with_dsl_file(yaml_path)
            .build()
        )

        assert json_extension.runtime.settings.max_connections == 3
        assert yaml_extension.runtime.settings.max_connections == 3
        assert json_extension.runtime.registry.get_type("dslfake").kind == "customdsl"
        assert yaml_extension.runtime.registry.get_type("dslfake").kind == "customdsl"
    finally:
        json_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)
        artifacts_dir.rmdir()


def test_plugin_entrypoints_extend_registry_and_openapi(monkeypatch) -> None:
    monkeypatch.setattr(
        "db_connection.plugins.entry_points",
        lambda: FakeEntryPoints(
            [FakeEntryPoint("test-plugin", "db_connection.plugins", bootstrap_test_plugin)]
        ),
    )

    extension = (
        DBConnectionExtension.builder()
        .with_uow_factory(build_uow_factory())
        .with_default_types(False)
        .with_plugin_entrypoints(names=["test-plugin"])
        .build()
    )
    app = FastAPI()
    extension.install(app)

    with TestClient(app) as client:
        types_response = client.get("/db-connections/types")
        assert types_response.status_code == 200
        plugin_spec = next(item for item in types_response.json() if item["name"] == "pluginfake")
        assert plugin_spec["kind"] == "plugin"

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        request_schema = openapi.json()["paths"]["/db-connections"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        schema_ref = request_schema.get("$ref")
        refs = [schema_ref] if schema_ref is not None else [item["$ref"] for item in request_schema["anyOf"]]
        assert any("PluginfakePluginNoDriverConnectionCreateRequest" in ref for ref in refs)


def test_empty_registry_openapi_uses_plain_string_query_parameters() -> None:
    extension = (
        DBConnectionExtension.builder()
        .with_uow_factory(build_uow_factory())
        .with_default_types(False)
        .build()
    )
    app = FastAPI()
    extension.install(app)

    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        openapi = response.json()

    kind_schema = _get_parameter_schema(
        openapi,
        path="/db-connections",
        method="get",
        parameter_name="kind",
    )
    type_schema = _get_parameter_schema(
        openapi,
        path="/db-connections",
        method="get",
        parameter_name="type",
    )

    assert kind_schema == {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Kind"}
    assert type_schema == {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Type"}


class HeaderOwnershipResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def resolve_create(self, ctx, draft):
        self.calls.append((ctx.operation, ctx.actor))
        extra = dict(draft.extra)
        extra["owner_id"] = ctx.actor["owner_id"]
        return replace(draft, extra=extra)

    async def resolve_patch(self, ctx, existing, patch):
        raise AssertionError("resolve_patch should not be called in this test")


def get_check_actor(x_owner_id: str = Header(...)) -> dict[str, str]:
    return {"owner_id": x_owner_id}


def test_check_endpoint_uses_actor_dependency_for_ownership_resolution() -> None:
    resolver = HeaderOwnershipResolver()
    extension = (
        DBConnectionExtension.builder()
        .with_uow_factory(build_uow_factory())
        .with_actor_dependency(get_check_actor)
        .with_ownership_resolver(resolver)
        .build()
    )
    app = FastAPI()
    extension.install(app)

    with TestClient(app) as client:
        response = client.post(
            "/db-connections/check",
            headers={"x-owner-id": "owner-http"},
            json=build_postgres_payload(name="Checked over HTTP"),
        )

    assert response.status_code == 200
    assert resolver.calls == [("check_payload", {"owner_id": "owner-http"})]


def test_builder_registry_merge_overwrites_same_name_specs() -> None:
    registry = ConnectionRegistry()
    registry.register_kind(KindSpec(name="sql", capabilities={"custom"}))
    registry.register_type(
        TypeSpec(
            name="postgres",
            kind="sql",
            properties_model=BuilderDSLProperties,
            public_model=BuilderDSLProperties,
            connector_factory=BuilderDSLConnector,
            tags={"custom"},
        )
    )

    extension = DBConnectionExtension.builder().with_uow_factory(build_uow_factory()).with_registry(registry).build()

    assert extension.runtime.registry.get_kind("sql").capabilities == {"custom"}
    assert extension.runtime.registry.get_type("postgres").properties_model is BuilderDSLProperties
    assert extension.runtime.registry.get_type("postgres").connector_factory is BuilderDSLConnector
    assert extension.runtime.registry.get_type("postgres").tags == {"custom"}


def test_register_type_with_overwrite_still_requires_known_kind() -> None:
    registry = ConnectionRegistry()

    with pytest.raises(ValidationFailedError, match="Unknown kind 'missing' for type 'broken'."):
        registry.register_type(
            TypeSpec(
                name="broken",
                kind="missing",
                properties_model=BuilderDSLProperties,
            ),
            overwrite=True,
        )
