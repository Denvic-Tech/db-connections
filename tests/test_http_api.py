from __future__ import annotations

import asyncio
import json

import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi import FastAPI, Header
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from db_connection import (
    DBConnectionExtension,
    DefaultSQLModelConnectionUnitOfWorkFactory,
    FernetEncryptionProvider,
)


def _get_parameter_schema(openapi: dict, *, path: str, method: str, parameter_name: str) -> dict:
    parameters = openapi["paths"][path][method]["parameters"]
    return next(parameter["schema"] for parameter in parameters if parameter["name"] == parameter_name)


async def _update_stored_connection(session_factory, model_class, connection_id: str, **values) -> None:
    statement = sa.update(model_class.__table__).where(model_class.id == connection_id).values(**values)
    async with session_factory() as session:
        await session.exec(statement)
        await session.commit()


def _unexpected_uow_factory():
    raise AssertionError("Unit of work factory should not be called in this test.")


def test_crud_flow_and_secret_hiding(client, uow_factory, postgres_payload: dict) -> None:
    create_response = client.post("/db-connections", json=postgres_payload)
    assert create_response.status_code == 200
    created = create_response.json()

    assert created["name"] == postgres_payload["name"]
    assert created["kind"] == "sql"
    assert created["type"] == "postgres"
    assert created["properties"]["database"] == "analytics"
    assert "secrets" not in created
    assert created["labels"]["env"] == "test"
    assert created["metadata"]["team"] == "data-platform"

    connection_id = created["id"]

    async def load_stored():
        async with uow_factory() as uow:
            return await uow.connections.get(connection_id)

    stored = asyncio.run(load_stored())
    assert stored is not None
    assert stored.secrets["password"] == "super-secret"

    list_response = client.get("/db-connections")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get(f"/db-connections/{connection_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == connection_id

    update_response = client.patch(
        f"/db-connections/{connection_id}",
        json={
            "name": "Renamed Postgres",
            "metadata": {"team": "core-platform"},
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["name"] == "Renamed Postgres"
    assert updated["metadata"]["team"] == "core-platform"

    check_response = client.post(f"/db-connections/{connection_id}/check", json={})
    assert check_response.status_code == 200
    checked = check_response.json()
    assert checked["name"] == "Renamed Postgres"
    assert checked["connected"] is False
    assert checked["exception"] is not None

    delete_response = client.delete(f"/db-connections/{connection_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["id"] == connection_id

    missing_response = client.get(f"/db-connections/{connection_id}")
    assert missing_response.status_code == 404
    detail = missing_response.json()["detail"]
    assert detail["code"] == "connection_not_found"


def test_types_endpoint_returns_runtime_schemas(client) -> None:
    response = client.get("/db-connections/types")
    assert response.status_code == 200
    payload = response.json()

    postgres = next(item for item in payload if item["name"] == "postgres")
    assert postgres["kind"] == "sql"
    assert "host" in postgres["properties_schema"]["properties"]
    assert "password" in postgres["secrets_schema"]["properties"]
    assert postgres["drivers"]
    assert postgres["supported_drivers"] == ["asyncpg", "psycopg", "psycopg2"]

    mssql = next(item for item in payload if item["name"] == "mssql")
    assert {driver["name"] for driver in mssql["drivers"]} == {"aioodbc", "pyodbc"}
    assert "anyOf" in mssql["properties_schema"]
    mssql_property_defs = mssql["properties_schema"]["$defs"]
    assert "MSSQLTCPProperties" in mssql_property_defs
    assert "MSSQLNamedInstanceProperties" in mssql_property_defs
    assert "port" in mssql_property_defs["MSSQLTCPProperties"]["properties"]
    assert "instance_name" in mssql_property_defs["MSSQLNamedInstanceProperties"]["properties"]
    pyodbc = next(driver for driver in mssql["drivers"] if driver["name"] == "pyodbc")
    assert "odbc_driver_name" in pyodbc["options_schema"]["properties"]
    assert "driver_name" not in pyodbc["options_schema"]["properties"]

    kafka = next(item for item in payload if item["name"] == "kafka")
    assert kafka["kind"] == "queue"
    assert "bootstrap_servers" in kafka["properties_schema"]["properties"]


def test_openapi_contains_typed_and_default_create_models(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    openapi = response.json()

    request_body_schema = openapi["paths"]["/db-connections"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    any_of_refs = [item["$ref"] for item in request_body_schema["anyOf"]]

    assert "#/components/schemas/ConnectionCreateRequest" not in any_of_refs
    assert any("PostgresSqlPsycopgDefaultDriverConnectionCreateRequest" in ref for ref in any_of_refs)
    assert any("MssqlSqlPyodbcDefaultDriverConnectionCreateRequest" in ref for ref in any_of_refs)

    components = openapi["components"]["schemas"]
    mssql_schema = components["MssqlSqlPyodbcDefaultDriverConnectionCreateRequest"]
    driver_options = mssql_schema["properties"]["driver_options"]
    assert "ODBCDriverOptions" in driver_options["$ref"]


def test_openapi_list_query_parameters_include_known_values_and_arbitrary_string(client) -> None:
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

    assert {"enum": ["file", "queue", "sql"], "type": "string"} in kind_schema["anyOf"]
    assert {"type": "string"} in kind_schema["anyOf"]
    assert {
        "enum": ["clickhouse", "ftp", "kafka", "mongodb", "mssql", "mysql", "oracle", "postgres", "s3", "sftp"],
        "type": "string",
    } in type_schema["anyOf"]
    assert {"type": "string"} in type_schema["anyOf"]


def test_mssql_payload_accepts_driver_name_alias_and_returns_canonical_driver_options(
    client,
    uow_factory,
    mssql_payload: dict,
) -> None:
    create_response = client.post("/db-connections", json=mssql_payload)

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["driver"] is None
    assert created["driver_options"] == {
        "odbc_driver_name": "ODBC Driver 18 for SQL Server",
    }

    async def load_stored():
        async with uow_factory() as uow:
            return await uow.connections.get(created["id"])

    stored = asyncio.run(load_stored())
    assert stored is not None
    assert stored.driver_options.odbc_driver_name == "ODBC Driver 18 for SQL Server"


def test_list_and_get_return_broken_rows_instead_of_failing(
    client,
    session_factory,
    stored_connection_model,
    postgres_payload: dict,
) -> None:
    valid_response = client.post("/db-connections", json=postgres_payload | {"name": "Healthy"})
    broken_response = client.post("/db-connections", json=postgres_payload | {"name": "Broken"})

    assert valid_response.status_code == 200
    assert broken_response.status_code == 200

    broken_id = broken_response.json()["id"]
    asyncio.run(
        _update_stored_connection(
            session_factory,
            stored_connection_model,
            broken_id,
            properties_json={"server": "127.0.0.1", "share": "/samba/public", "username": "test"},
        )
    )

    list_response = client.get("/db-connections")
    assert list_response.status_code == 200
    payload = {item["name"]: item for item in list_response.json()}
    assert payload["Healthy"]["type"] == "postgres"
    assert payload["Broken"]["state"] == "invalid"
    assert payload["Broken"]["raw_properties"] == {
        "server": "127.0.0.1",
        "share": "/samba/public",
        "username": "test",
    }
    assert [issue["code"] for issue in payload["Broken"]["issues"]] == ["invalid_properties"]

    get_response = client.get(f"/db-connections/{broken_id}")
    assert get_response.status_code == 200
    assert get_response.json()["state"] == "invalid"


def test_unreadable_secrets_require_repair_payload(
    client,
    session_factory,
    stored_connection_model,
    postgres_payload: dict,
) -> None:
    create_response = client.post("/db-connections", json=postgres_payload)
    assert create_response.status_code == 200
    connection_id = create_response.json()["id"]

    asyncio.run(
        _update_stored_connection(
            session_factory,
            stored_connection_model,
            connection_id,
            secrets_ciphertext="not-json",
        )
    )

    get_response = client.get(f"/db-connections/{connection_id}")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["state"] == "invalid"
    assert [issue["code"] for issue in payload["issues"]] == ["unreadable_secrets"]
    assert "raw_secrets" not in payload or payload["raw_secrets"] is None

    patch_response = client.patch(
        f"/db-connections/{connection_id}",
        json={"metadata": {"team": "repair"}},
    )
    assert patch_response.status_code == 422
    assert patch_response.json()["detail"]["details"] == {"repair_required": ["secrets"]}

    check_response = client.post(f"/db-connections/{connection_id}/check", json={})
    assert check_response.status_code == 422
    assert check_response.json()["detail"]["details"] == {"repair_required": ["secrets"]}

    repair_response = client.patch(
        f"/db-connections/{connection_id}",
        json={
            "metadata": {"team": "repair"},
            "secrets": {"password": "repaired-secret"},
        },
    )
    assert repair_response.status_code == 200
    assert "state" not in repair_response.json()

    repaired_get = client.get(f"/db-connections/{connection_id}")
    assert repaired_get.status_code == 200
    assert "state" not in repaired_get.json()


def test_fernet_decryption_failure_returns_broken_rows_for_list_and_get(
    session_factory,
    stored_connection_model,
    postgres_payload: dict,
) -> None:
    encryption_provider = FernetEncryptionProvider(Fernet.generate_key())
    extension = DBConnectionExtension(
        uow_factory=DefaultSQLModelConnectionUnitOfWorkFactory(
            session_factory,
            model_class=stored_connection_model,
            encryption_provider=encryption_provider,
        ),
        encryption_provider=encryption_provider,
    )
    app = FastAPI()
    extension.install(app)

    with TestClient(app) as fernet_client:
        healthy_response = fernet_client.post("/db-connections", json=postgres_payload | {"name": "Healthy"})
        broken_response = fernet_client.post("/db-connections", json=postgres_payload | {"name": "Broken Fernet"})

        assert healthy_response.status_code == 200
        assert broken_response.status_code == 200

        broken_id = broken_response.json()["id"]
        wrong_key_provider = FernetEncryptionProvider(Fernet.generate_key())
        asyncio.run(
            _update_stored_connection(
                session_factory,
                stored_connection_model,
                broken_id,
                secrets_ciphertext=wrong_key_provider.encrypt({"password": "wrong-key-secret"}),
            )
        )

        list_response = fernet_client.get("/db-connections")
        assert list_response.status_code == 200
        payload = {item["name"]: item for item in list_response.json()}
        assert "state" not in payload["Healthy"]
        assert payload["Broken Fernet"]["state"] == "invalid"
        assert [issue["code"] for issue in payload["Broken Fernet"]["issues"]] == ["unreadable_secrets"]
        assert payload["Broken Fernet"].get("raw_secrets") is None

        get_response = fernet_client.get(f"/db-connections/{broken_id}")
        assert get_response.status_code == 200
        assert get_response.json()["state"] == "invalid"
        assert [issue["code"] for issue in get_response.json()["issues"]] == ["unreadable_secrets"]


def test_decrypted_invalid_secrets_are_exposed_as_raw_json_for_repair(
    client,
    session_factory,
    stored_connection_model,
) -> None:
    create_response = client.post(
        "/db-connections",
        json={
            "name": "Broken S3",
            "kind": "file",
            "type": "s3",
            "properties": {
                "bucket": "test-bucket",
                "prefix": "backups",
            },
            "secrets": {
                "access_token_id": "access-key",
                "access_token_key": "secret-key",
            },
        },
    )
    assert create_response.status_code == 200
    connection_id = create_response.json()["id"]

    asyncio.run(
        _update_stored_connection(
            session_factory,
            stored_connection_model,
            connection_id,
            secrets_ciphertext=json.dumps({}),
        )
    )

    get_response = client.get(f"/db-connections/{connection_id}")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["state"] == "invalid"
    assert payload["raw_secrets"] == {}
    assert [issue["code"] for issue in payload["issues"]] == ["invalid_secrets"]


def test_route_exceptions_are_logged_with_traceback(client, caplog) -> None:
    with caplog.at_level("ERROR", logger="db_connection.fastapi.extension"):
        response = client.get("/db-connections", params={"labels": "[]"})

    assert response.status_code == 422
    assert any("list_connections" in record.getMessage() for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)


def test_extension_routes_use_custom_traceback_logging_route(app: FastAPI) -> None:
    extension_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/db-connections")
    ]

    assert extension_routes
    assert len(extension_routes) == 9
    assert {type(route) for route in extension_routes} == {type(extension_routes[0])}
    assert type(extension_routes[0]) is not APIRoute
    assert issubclass(type(extension_routes[0]), APIRoute)


def test_kinds_route_logs_traceback_for_unexpected_errors(
    client,
    extension: DBConnectionExtension,
    caplog,
) -> None:
    def fail_list_kinds() -> list:
        raise RuntimeError("boom")

    extension.runtime.service.list_kinds = fail_list_kinds  # type: ignore[method-assign]

    with caplog.at_level("ERROR", logger="db_connection.fastapi.extension"):
        response = client.get("/db-connections/kinds")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "internal_error",
        "message": "Internal server error.",
        "details": {},
    }
    assert any("list_kinds" in record.getMessage() for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)


def test_dependency_errors_are_logged_and_mapped(caplog) -> None:
    def get_actor() -> dict[str, str]:
        raise RuntimeError("dependency failed")

    app = FastAPI()
    extension = DBConnectionExtension(uow_factory=_unexpected_uow_factory, get_actor=get_actor)
    extension.install(app)

    with caplog.at_level("ERROR", logger="db_connection.fastapi.extension"), TestClient(app) as client:
        response = client.get("/db-connections")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "internal_error",
        "message": "Internal server error.",
        "details": {},
    }
    assert any("list_connections" in record.getMessage() for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)


def test_dependency_validation_errors_are_logged_and_preserve_fastapi_response(caplog) -> None:
    def get_actor(x_actor_id: str = Header(...)) -> dict[str, str]:
        return {"actor_id": x_actor_id}

    app = FastAPI()
    extension = DBConnectionExtension(uow_factory=_unexpected_uow_factory, get_actor=get_actor)
    extension.install(app)

    with caplog.at_level("ERROR", logger="db_connection.fastapi.extension"), TestClient(app) as client:
        response = client.get("/db-connections")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"][-1] == "x-actor-id"
    assert detail[0]["type"] == "missing"
    assert any("list_connections" in record.getMessage() for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)
