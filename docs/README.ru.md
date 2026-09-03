# DB Connection

[English](../README.md)

![Python Support](https://img.shields.io/badge/python-3.11+-blue.svg)
![Pydantic Version](https://img.shields.io/badge/pydantic-v2-orange.svg)
![SQLModel Version](https://img.shields.io/badge/sqlmodel-0.0.24+-purple.svg)

`db-connection` — это расширяемая платформа для работы с подключениями к
сервисам в consumer-проектах. Библиотека предоставляет:

- доменные модели для черновиков подключений, сохраненных записей и результатов
  валидации;
- registry `kind` и `type` спецификаций;
- встроенные коннекторы для SQL, Kafka, S3, FTP и SFTP;
- FastAPI extension с CRUD, health-check и runtime schema endpoints;
- extension points для custom repository/UoW, API-схем, access policy и
  error mapping.

Текущий API построен вокруг `DBConnectionExtension` и
`DBConnectionExtension.builder()`. Это заменяет старый подход, где глобальный
router мутировал общее состояние модулей.

## Базовые концепции

- `kind` — категория подключения, например `sql`, `queue`, `file`.
- `type` — конкретная реализация внутри категории, например `postgres`,
  `kafka`, `s3`.
- `driver` — идентификатор runtime-адаптера, например `psycopg`, `pyodbc`,
  `aioodbc`, `native`.
- `driver_options` — отдельный top-level канал для типизированных параметров
  конкретного драйвера.
- `TypeSpec` описывает runtime validation, public schema, driver specs и
  connector factories для одного типа подключения.
- `ConnectionRegistry` — runtime registry всех kinds и types, доступных в одном
  экземпляре приложения.
- `DBConnectionExtension` — граница FastAPI-интеграции. Она владеет runtime
  settings, service layer, registry, access policy и error mapper для одного
  приложения.

## Установка

Установка напрямую из GitHub:

```bash
python -m pip install git+https://github.com/Denvic-Tech/db-connections.git
```

Для локальной разработки с драйверами, async-адаптерами и test tooling:

```bash
python -m pip install -e .[drivers,async,test,s3]
```

Исходный код: <https://github.com/Denvic-Tech/db-connections>.

## Быстрый старт

Минимальная настройка с default registry и встроенным async
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

После установки extension в FastAPI появляются:

- `GET /db-connections/kinds`
- `GET /db-connections/types`
- `GET /db-connections`
- `POST /db-connections`
- `GET /db-connections/{connection_id}`
- `PATCH /db-connections/{connection_id}`
- `DELETE /db-connections/{connection_id}`
- `POST /db-connections/check`
- `POST /db-connections/{connection_id}/check`

Endpoint `GET /db-connections/types` особенно полезен в consumer-проектах,
потому что возвращает JSON Schema для runtime-зарегистрированных типов и
driver-level schema для `driver_options`.

## Встроенные типы

В default registry входят:

- `sql`: `postgres`, `mysql`, `clickhouse`, `mssql`, `oracle`, `mongodb`
- `queue`: `kafka`
- `file`: `s3`, `ftp`, `sftp`

Для каждого встроенного типа уже определены:

- `properties_model`
- `secrets_model`
- `public_model`
- driver specs / supported drivers
- единый async `connector_factory`

Для части runtime-коннекторов consumer-приложению нужно отдельно установить
соответствующий optional driver или SDK.

## Runtime settings

`DBConnectionSettings` являются instance-based и immutable. Чтобы обновить
настройки во время работы приложения, нужно отправить patch в активный
extension instance:

```python
updated = extension.update_settings(max_connections=250)
assert updated.max_connections == 250
```

Это атомарно пересоздает service layer без мутации глобального состояния
модулей.

## Примеры для consumer-проектов

### Custom Repository

Если проект хранит дополнительные колонки, например `project_id`, `owner_id`
или `environment`, реализуйте протокол `ConnectionRepository` и отображайте эти
колонки в `ConnectionRecord.extra`. Репозиторий должен быть session-bound, а
граница транзакции должна жить в `ConnectionUnitOfWork`.

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

Полный рабочий пример находится в `app/main.py`.

### Custom API Schemas

Если проекту нужны собственные поля в request/response, передайте свой
`APISchemaSet`:

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

Дальше подключите их через builder:

```python
extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_api_schemas(api_schemas)
    .build()
)
```

Это рекомендуемый способ, если consumer-проекту нужен стабильный OpenAPI
контракт со своими дополнительными полями.

### Access Policy

Project-specific access control должен жить в `AccessPolicy`, а не в route-ах.
Библиотека вызывает policy для list, create, read, update и delete use case-ов.

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

Извлечение actor задается отдельно через dependency injection FastAPI:

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

Application layer выбрасывает нормализованные library exceptions.
Consumer-проект может преобразовать их в свои HTTP status codes и error codes
через `ErrorMapper`.

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

Подключение через builder:

```python
extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_error_mapper(ProjectErrorMapper())
    .build()
)
```

### Custom Kind и Type

Расширение registry делается явно и scoped на экземпляр extension. Consumer-
проект может добавить свои kinds и types без изменения исходников библиотеки.

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

Новые kind и type автоматически появляются в:

- `GET /db-connections/kinds`
- `GET /db-connections/types`
- runtime validation
- `POST /db-connections/check`

## DSL и плагины

Builder также поддерживает декларативную настройку:

```python
extension = (
    DBConnectionExtension.builder()
    .with_uow_factory(uow_factory)
    .with_dsl_file("db-connection.yaml")
    .with_plugin_entrypoints(names=["my-project-plugin"])
    .build()
)
```

Доступные builder hooks:

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

## Демо-приложение

`app/main.py` показывает полный сценарий интеграции в consumer-проект:

- custom SQLModel persistence table;
- custom repository и UoW с шифрованием секретов;
- custom API schemas с `project_id`, `owner_id`, `environment`;
- actor-based access policy;
- project-specific error mapper;
- custom runtime kind и type (`service/httpapi`);
- endpoint для runtime settings update.

Запускать нужно через virtual environment репозитория:

```bash
python -m uvicorn app.main:app --reload --port 3000
```

После запуска можно посмотреть:

- `GET /docs`
- `GET /db-connections/types`
- `GET /demo/examples`
- `POST /demo/settings/max-connections/{limit}`

## Тестирование

Запуск полного набора тестов:

```bash
python -m pytest
```

Если Docker-based сервисы недоступны:

```bash
python -m pytest -m "not docker_required"
```

## Публикация в PyPI

Сначала соберите дистрибутивы:

```bash
python -m build
```

Для локальной публикации maintainer-ом задайте `PYPI_API_TOKEN` в окружении
(или в локальном игнорируемом `.env`) и выполните:

```bash
python scripts/upload_builds.py
```

Helper сначала проверяет артефакты через `twine check`, затем публикует их в
PyPI. Для проверки через TestPyPI можно явно выбрать repository:

```bash
python scripts/upload_builds.py --repository testpypi
```

Для автоматической публикации из GitHub рекомендуется PyPI Trusted
Publishing/OIDC вместо долгоживущего API token. См.
[документацию PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/).

## Лицензия

DB Connection распространяется по GNU Affero General Public License v3.0.
Условия см. в [LICENSE](../LICENSE) и [COPYING](../COPYING).

## Примечания

- Секреты нельзя коммитить в репозиторий. Используйте `.env` или внешний secret
  manager.
- Встроенный `DefaultSQLModelConnectionRepository` является session-bound
  адаптером. Для типового async SQLModel-сценария используйте его вместе с
  `DefaultSQLModelConnectionUnitOfWorkFactory`.
- Подготовка таблиц больше не выполняется репозиторием автоматически. Используйте
  миграции или явный `SQLModel.metadata.create_all(...)` на старте приложения.
- Библиотека поддерживает project-specific HTTP behavior через `AccessPolicy` и
  `ErrorMapper`, не связывая domain/application code с FastAPI route-ами.
