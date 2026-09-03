# DB Connection

[Русский](docs/README.ru.md)

![Python Support](https://img.shields.io/badge/python-3.11+-blue.svg)
![Pydantic Version](https://img.shields.io/badge/pydantic-v2-orange.svg)
![SQLModel Version](https://img.shields.io/badge/sqlmodel-0.0.24+-purple.svg)

`db-connection` is an extensible Python library for storing, validating, exposing,
and checking service connection definitions in consumer applications. It provides:

- domain models for connection drafts, stored records, and validation results;
- a runtime registry of `kind` and `type` specifications;
- built-in connectors for SQL, Kafka, S3, FTP, and SFTP;
- a FastAPI extension with CRUD, health-check, and runtime schema endpoints;
- extension points for custom repositories/UoW, API schemas, access policies, and
  error mapping.

The current API is built around `DBConnectionExtension` and
`DBConnectionExtension.builder()`. This replaces the legacy approach where a
global router mutated shared module state.

## Core Concepts

- `kind` — a connection category, for example `sql`, `queue`, or `file`.
- `type` — a concrete implementation inside a category, for example `postgres`,
  `kafka`, or `s3`.
- `driver` — a runtime adapter identifier, for example `psycopg`, `pyodbc`,
  `aioodbc`, or `native`.
- `driver_options` — a separate top-level channel for typed driver-specific
  parameters.
- `TypeSpec` describes runtime validation, public schemas, driver specs, and
  connector factories for one connection type.
- `ConnectionRegistry` is the runtime registry of all kinds and types available
  to one application instance.
- `DBConnectionExtension` is the FastAPI integration boundary. It owns runtime
  settings, the service layer, registry, access policy, and error mapper for one
  application.

## Installation

Install directly from GitHub:

```bash
python -m pip install git+https://github.com/Denvic-Tech/db-connections.git
```

For local development with database drivers, async adapters, and test tooling:

```bash
python -m pip install -e .[drivers,async,test,s3]
```

Source code: <https://github.com/Denvic-Tech/db-connections>.

## Quick Start

Minimal setup with the default registry and the built-in async
`DefaultSQLModelConnectionUnitOfWorkFactory`:

```python
import asyncio

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from db_connection import (
    DBConnectionExtension,
    DefaultSQLModelConnectionUnitOfWorkFactory,
    DefaultStoredConnection,
)


class StoredConnection(DefaultStoredConnection, table=True):
    __tablename__ = "db_connections"

engine = create_async_engine(
    "sqlite+aiosqlite:///./db_connection.db",
    connect_args={"check_same_thread": False},
)


async def prepare_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)


asyncio.run(prepare_schema())

session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
uow_factory = DefaultSQLModelConnectionUnitOfWorkFactory(
    session_factory,
    model_class=StoredConnection,
)

extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_max_connections(100)
    .build()
)

app = FastAPI()
extension.install(app, prefix="/db-connections")
```

After installing the extension into FastAPI, the following endpoints are
available:

- `GET /db-connections/kinds`
- `GET /db-connections/types`
- `GET /db-connections`
- `POST /db-connections`
- `GET /db-connections/{connection_id}`
- `PATCH /db-connections/{connection_id}`
- `DELETE /db-connections/{connection_id}`
- `POST /db-connections/check`
- `POST /db-connections/{connection_id}/check`

`GET /db-connections/types` is especially useful for consumer applications
because it returns JSON Schema for runtime-registered connection types and
per-driver schemas for `driver_options`.

## Built-in Types

The default registry includes:

- `sql`: `postgres`, `mysql`, `clickhouse`, `mssql`, `oracle`, `mongodb`
- `queue`: `kafka`
- `file`: `s3`, `ftp`, `sftp`

Each built-in type defines:

- `properties_model`
- `secrets_model`
- `public_model`
- driver specs / supported drivers
- a unified async `connector_factory`

Some runtime connectors require their corresponding optional third-party driver
or SDK to be installed by the consumer application.

## Runtime Settings

`DBConnectionSettings` are instance-based and immutable. To update settings while
the application is running, send a patch to the active extension instance:

```python
updated = extension.update_settings(max_connections=250)
assert updated.max_connections == 250
```

This atomically rebuilds the service layer without mutating global module state.

## Consumer Application Examples

### Custom Repository

If the consumer application stores additional columns such as `project_id`,
`owner_id`, or `environment`, implement the `ConnectionRepository` protocol and
map those columns to `ConnectionRecord.extra`. The repository should be
session-bound, while the transaction boundary should live in
`ConnectionUnitOfWork`.

```python
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import Field, SQLModel

from db_connection import ConnectionDraft, ConnectionListQuery, ConnectionRecord, StoredConnectionRecordMapper


class ProjectStoredConnection(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    kind: str
    type: str
    project_id: int
    owner_id: str
    environment: str
    properties_json: dict[str, Any] = {}
    secrets_ciphertext: str = "{}"
    labels_json: dict[str, str] = {}
    metadata_json: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None


class ProjectConnectionRepository:
    def __init__(self, session: AsyncSession, encryption_provider) -> None:
        self._session = session
        self._encryption_provider = encryption_provider
        self._record_mapper = StoredConnectionRecordMapper(encryption_provider=encryption_provider)
        ...

    async def create(self, draft: ConnectionDraft) -> ConnectionRecord:
        row = ProjectStoredConnection(
            id=str(uuid4()),
            name=draft.name,
            kind=draft.kind,
            type=draft.type,
            project_id=int(draft.extra["project_id"]),
            owner_id=str(draft.extra["owner_id"]),
            environment=str(draft.extra["environment"]),
            properties_json=draft.properties,
            secrets_ciphertext=self._encryption_provider.encrypt(draft.secrets),
            labels_json=draft.labels,
            metadata_json=draft.metadata,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_record(row)

    async def list(self, query: ConnectionListQuery) -> list[ConnectionRecord]:
        ...

    async def get(self, connection_id: str) -> ConnectionRecord | None:
        ...

    async def replace(self, connection_id: str, draft: ConnectionDraft) -> ConnectionRecord | None:
        ...

    async def delete(self, connection_id: str) -> ConnectionRecord | None:
        ...

    def _to_record(self, row: ProjectStoredConnection) -> ConnectionRecord:
        return self._record_mapper.to_record(
            id=row.id,
            name=row.name,
            kind=row.kind,
            type=row.type,
            driver=None,
            properties_json=row.properties_json,
            secrets_ciphertext=row.secrets_ciphertext,
            labels_json=row.labels_json,
            metadata_json=row.metadata_json,
            extra={
                "project_id": row.project_id,
                "owner_id": row.owner_id,
                "environment": row.environment,
            },
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )
```

A complete working example is available in `app/main.py`.

### Custom API Schemas

If the consumer application needs custom request/response fields, provide a
custom `APISchemaSet`:

```python
from typing import Literal

from db_connection import APISchemaSet, ConnectionCreateRequest
from db_connection import ConnectionReadResponse, ConnectionUpdateRequest


class ProjectConnectionCreate(ConnectionCreateRequest):
    project_id: int
    owner_id: str
    environment: Literal["dev", "stage", "prod"]


class ProjectConnectionUpdate(ConnectionUpdateRequest):
    project_id: int | None = None
    owner_id: str | None = None
    environment: Literal["dev", "stage", "prod"] | None = None


class ProjectConnectionRead(ConnectionReadResponse):
    project_id: int
    owner_id: str
    environment: Literal["dev", "stage", "prod"]


api_schemas = APISchemaSet(
    create=ProjectConnectionCreate,
    read=ProjectConnectionRead,
    update=ProjectConnectionUpdate,
)
```

Then register the schema set through the builder:

```python
extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_api_schemas(api_schemas)
    .build()
)
```

This is the recommended approach when a consumer application needs a stable
OpenAPI contract with project-specific fields.

### Access Policy

Project-specific access control should live in `AccessPolicy`, not in routes.
The library invokes the policy for list, create, read, update, and delete use
cases.

```python
from typing import Any

from db_connection import AccessContext, AccessDeniedError, ConnectionListQuery, ConnectionRecord


class ProjectAccessPolicy:
    async def scope_list(self, ctx: AccessContext, query: ConnectionListQuery) -> ConnectionListQuery:
        extra_filters = dict(query.extra_filters)
        extra_filters["owner_id"] = ctx.actor["owner_id"]
        return query.model_copy(update={"extra_filters": extra_filters})

    async def can_create(self, ctx: AccessContext) -> None:
        if ctx.payload and ctx.payload["owner_id"] != ctx.actor["owner_id"]:
            raise AccessDeniedError("Actor cannot create a connection for another owner.")

    async def can_get_one(self, ctx: AccessContext, connection: ConnectionRecord) -> None:
        if connection.extra["owner_id"] != ctx.actor["owner_id"]:
            raise AccessDeniedError("Connection belongs to another owner.")

    async def can_update(self, ctx: AccessContext, connection: ConnectionRecord, patch: dict[str, Any]) -> None:
        if connection.extra["owner_id"] != ctx.actor["owner_id"]:
            raise AccessDeniedError("Connection belongs to another owner.")

    async def can_delete(self, ctx: AccessContext, connection: ConnectionRecord) -> None:
        if connection.extra["owner_id"] != ctx.actor["owner_id"]:
            raise AccessDeniedError("Connection belongs to another owner.")
```

Actor extraction is configured separately through FastAPI dependency injection:

```python
from fastapi import Header


def get_actor(x_owner_id: str = Header(...)) -> dict[str, str]:
    return {"owner_id": x_owner_id}


extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_access_policy(ProjectAccessPolicy())
    .with_actor_dependency(get_actor)
    .build()
)
```

### Custom Error Mapper

The application layer raises normalized library exceptions. A consumer
application can map them to project-specific HTTP status codes and error codes
through `ErrorMapper`.

```python
from db_connection import AccessDeniedError, ErrorMapper, ErrorResponseSpec
from db_connection import ValidationFailedError


class ProjectErrorMapper(ErrorMapper):
    def map_exception(self, exc: Exception) -> ErrorResponseSpec:
        if isinstance(exc, AccessDeniedError):
            return ErrorResponseSpec(
                status_code=404,
                code="project_connection_hidden",
                message="Connection was not found in the current project scope.",
            )
        if isinstance(exc, ValidationFailedError):
            return ErrorResponseSpec(
                status_code=422,
                code="project_connection_invalid",
                message=exc.message,
                details=exc.details,
            )
        return super().map_exception(exc)
```

Register it through the builder:

```python
extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_error_mapper(ProjectErrorMapper())
    .build()
)
```

### Custom Kind and Type

Registry extensions are explicit and scoped to one extension instance. A
consumer application can add custom kinds and types without modifying the
library source code.

```python
from pydantic import AnyHttpUrl, BaseModel

from db_connection import Connector, ConnectionCheckResult
from db_connection import KindSpec, TypeSpec


class HTTPAPIProperties(BaseModel):
    base_url: AnyHttpUrl
    health_path: str = "/health"


class HTTPAPISecrets(BaseModel):
    api_token: str | None = None


class HTTPAPIConnector(Connector):
    async def check(self, connection) -> ConnectionCheckResult:
        return ConnectionCheckResult(
            name=connection.name,
            connected=True,
            message=f"Health endpoint: {connection.properties.base_url}{connection.properties.health_path}",
        )

    async def get_client(self, connection) -> dict[str, str]:
        return {"base_url": str(connection.properties.base_url)}


extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_kind(
        KindSpec(
            name="service",
            description="HTTP-based service integrations.",
            capabilities={"check", "client", "request"},
        )
    )
    .with_type(
        TypeSpec(
            name="httpapi",
            kind="service",
            properties_model=HTTPAPIProperties,
            secrets_model=HTTPAPISecrets,
            public_model=HTTPAPIProperties,
            connector_factory=HTTPAPIConnector,
            capabilities={"check", "client", "request"},
        )
    )
    .build()
)
```

New kinds and types automatically appear in:

- `GET /db-connections/kinds`
- `GET /db-connections/types`
- runtime validation
- `POST /db-connections/check`

## DSL and Plugins

The builder also supports declarative configuration:

```python
extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_dsl_file("db-connection.yaml")
    .with_plugin_entrypoints(names=["my-project-plugin"])
    .build()
)
```

Available builder hooks:

- `.with_uow_factory(...)`
- `.with_settings(...)`
- `.with_max_connections(...)`
- `.with_registry(...)`
- `.with_default_types(...)`
- `.with_kind(...)`
- `.with_type(...)`
- `.with_access_policy(...)`
- `.with_error_mapper(...)`
- `.with_api_schemas(...)`
- `.with_api_mapper(...)`
- `.with_actor_dependency(...)`
- `.with_plugin_entrypoints(...)`
- `.with_dsl_data(...)`
- `.with_dsl_file(...)`

## Demo Application

`app/main.py` demonstrates a complete consumer integration scenario:

- a custom SQLModel persistence table;
- a custom repository and UoW with secret encryption;
- custom API schemas with `project_id`, `owner_id`, and `environment`;
- actor-based access policy;
- project-specific error mapper;
- a custom runtime kind and type (`service/httpapi`);
- an endpoint for runtime settings updates.

Run it from the repository virtual environment:

```bash
python -m uvicorn app.main:app --reload --port 3000
```

After startup, inspect:

- `GET /docs`
- `GET /db-connections/types`
- `GET /demo/examples`
- `POST /demo/settings/max-connections/{limit}`

## Testing

Run the complete test suite:

```bash
python -m pytest
```

If Docker-backed services are unavailable:

```bash
python -m pytest -m "not docker_required"
```

## Publishing to PyPI

Build the distributions first:

```bash
python -m build
```

For a local maintainer release, set `PYPI_API_TOKEN` in the environment (or in a
local ignored `.env` file) and run:

```bash
python scripts/upload_builds.py
```

The helper validates the artifacts with `twine check` and then publishes them to
PyPI. TestPyPI can be selected explicitly:

```bash
python scripts/upload_builds.py --repository testpypi
```

For automated GitHub releases, PyPI Trusted Publishing/OIDC is preferred over a
long-lived API token. See the
[PyPI Trusted Publishing documentation](https://docs.pypi.org/trusted-publishers/).

## License

DB Connection is distributed under the GNU Affero General Public License v3.0.
See [LICENSE](LICENSE) and [COPYING](COPYING) for the applicable terms.

## Notes

- Never commit secrets to the repository. Use environment variables, a local
  ignored `.env` file, or an external secret manager.
- The built-in `DefaultSQLModelConnectionRepository` is a session-bound adapter.
  For a typical async SQLModel setup, use it together with
  `DefaultSQLModelConnectionUnitOfWorkFactory`.
- Table creation is no longer performed automatically by the repository. Use
  migrations or an explicit `SQLModel.metadata.create_all(...)` during
  application startup.
- The library supports project-specific HTTP behavior through `AccessPolicy` and
  `ErrorMapper` without coupling domain/application code to FastAPI routes.
