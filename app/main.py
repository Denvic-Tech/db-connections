"""Демонстрационное FastAPI-приложение с кастомным расширением `db_connection`.

Модуль показывает, как собрать инстанс библиотеки с собственной моделью
хранения, политикой доступа, API-схемами, обработкой ошибок и пользовательским
типом подключения.
"""

# pylint: disable=no-member,large-inline-collection,duplicate-code

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi import FastAPI, Header
from pydantic import AnyHttpUrl, BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from db_connection import (
    AccessContext,
    AccessDeniedError,
    APISchemaSet,
    ConnectionCheckResult,
    ConnectionCreateRequest,
    ConnectionDraft,
    ConnectionListQuery,
    ConnectionReadResponse,
    ConnectionRecord,
    ConnectionRepository,
    ConnectionUnitOfWork,
    ConnectionUnitOfWorkFactory,
    ConnectionUpdateRequest,
    Connector,
    DBConnectionExtension,
    ErrorMapper,
    ErrorResponseSpec,
    FernetEncryptionProvider,
    KindSpec,
    StoredConnectionRecordMapper,
    TypeSpec,
    ValidatedConnection,
    ValidationFailedError,
)
from db_connection._async_utils import run_async_blocking

DEMO_FERNET_KEY = os.getenv("DB_CONNECTION_DEMO_FERNET_KEY", Fernet.generate_key())
DATABASE_URL = os.getenv("DB_CONNECTION_DEMO_DATABASE_URL", "sqlite+aiosqlite:///./app/db_connection_demo.db")


class ProjectStoredConnection(SQLModel, table=True):
    """SQLModel-таблица для хранения подключений с проектными полями.

    Нужна примеру, чтобы показать, как библиотеку можно встроить в уже
    существующую схему данных и хранить вместе с подключением дополнительные
    атрибуты предметной области.
    """

    __tablename__ = "project_db_connections"

    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    kind: str = Field(index=True)
    type: str = Field(index=True)
    driver: str | None = Field(default=None)
    project_id: int = Field(index=True)
    owner_id: str = Field(index=True)
    environment: str = Field(index=True)
    properties_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(sa.JSON, nullable=False),
    )
    secrets_ciphertext: str = Field(default="{}")
    labels_json: dict[str, str] = Field(
        default_factory=dict,
        sa_column=sa.Column(sa.JSON, nullable=False),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(sa.JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    deleted_at: datetime | None = Field(default=None, nullable=True)


class ProjectConnectionCreate(ConnectionCreateRequest):
    """Схема создания подключения с обязательным проектным контекстом.

    Нужна для демонстрации того, как публичный API можно расширить полями,
    которые требуются конкретному приложению поверх базовой модели библиотеки.
    """

    project_id: int
    owner_id: str
    environment: Literal["dev", "stage", "prod"]


class ProjectConnectionUpdate(ConnectionUpdateRequest):
    """Схема частичного обновления подключения с проектными полями.

    Нужна, чтобы PATCH-запросы могли менять не только базовые параметры
    подключения, но и прикладные атрибуты вроде владельца и окружения.
    """

    project_id: int | None = None
    owner_id: str | None = None
    environment: Literal["dev", "stage", "prod"] | None = None


class ProjectConnectionRead(ConnectionReadResponse):
    """Схема чтения подключения, возвращаемая наружу через HTTP API.

    Нужна, чтобы в ответах API клиент видел дополнительные проектные данные,
    которые хранятся в репозитории и участвуют в бизнес-логике доступа.
    """

    project_id: int
    owner_id: str
    environment: Literal["dev", "stage", "prod"]


class HTTPAPIProperties(BaseModel):
    """Публичные свойства демонстрационного типа `httpapi`.

    Нужны для описания несекретной конфигурации HTTP-интеграции, которая
    валидируется схемой и участвует в проверке подключения.
    """

    base_url: AnyHttpUrl
    health_path: str = "/health"
    timeout_seconds: int = 5


class HTTPAPISecrets(BaseModel):
    """Секреты демонстрационного типа `httpapi`.

    Нужны, чтобы показать разделение обычных параметров и чувствительных данных,
    которые библиотека хранит отдельно и передает коннектору только при работе.
    """

    api_token: str | None = None


class HTTPAPIPublic(BaseModel):
    """Публичное представление типа `httpapi`, безопасное для выдачи клиенту.

    Нужна примеру, чтобы явно показать модель данных, которую можно раскрывать
    наружу без включения секретных значений.
    """

    base_url: AnyHttpUrl
    health_path: str = "/health"
    timeout_seconds: int = 5


class HTTPAPIConnector(Connector):
    """Демонстрационный коннектор для HTTP-сервиса.

    Нужен, чтобы показать регистрацию собственного типа подключения и две
    основные возможности коннектора: проверку доступности и сборку клиента.
    """

    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        """Проверяет, что демо-подключение выглядит пригодным для использования.

        В примере метод не делает сетевой запрос, а имитирует проверку и
        показывает, где в реальном проекте размещается логика health-check.
        """

        base_url = str(connection.properties.base_url)
        message = (
            f"Health endpoint: {base_url.rstrip('/')}{connection.properties.health_path}"
            if base_url.startswith("https://")
            else "Demo connector expects an https URL."
        )
        return ConnectionCheckResult(
            name=connection.name,
            connected=base_url.startswith("https://"),
            message=message,
        )

    async def get_client(self, connection: ValidatedConnection) -> dict[str, str]:
        """Возвращает упрощенный клиент для демонстрационного сценария.

        Нужен, чтобы показать, как коннектор может преобразовать валидированное
        подключение в runtime-объект, которым пользуется приложение.
        """

        return {
            "base_url": str(connection.properties.base_url),
            "health_path": connection.properties.health_path,
        }


class ProjectConnectionRepository(ConnectionRepository):
    """Репозиторий подключений, привязанный к проектной SQLModel-таблице.

    Нужен примеру, чтобы показать замену стандартного хранилища библиотеки на
    собственную реализацию с дополнительными полями и шифрованием секретов.
    """

    def __init__(self, session: AsyncSession, *, encryption_provider: FernetEncryptionProvider) -> None:
        """Инициализирует session-bound репозиторий поверх текущей транзакции."""

        self._session = session
        self._encryption_provider = encryption_provider
        self._record_mapper = StoredConnectionRecordMapper(encryption_provider=encryption_provider)

    async def create(self, draft: ConnectionDraft) -> ConnectionRecord:
        """Создает запись подключения из доменного черновика.

        Нужен, чтобы связать входную модель библиотеки с конкретной таблицей
        приложения и сохранить проектные поля вместе с секретами.
        """

        now = datetime.now(UTC)
        row = ProjectStoredConnection(
            id=str(uuid4()),
            name=draft.name,
            kind=draft.kind,
            type=draft.type,
            driver=draft.driver,
            project_id=self._require_int_extra(draft.extra, "project_id"),
            owner_id=self._require_str_extra(draft.extra, "owner_id"),
            environment=self._require_str_extra(draft.extra, "environment"),
            properties_json=draft.properties,
            secrets_ciphertext=self._encryption_provider.encrypt(draft.secrets),
            labels_json=draft.labels,
            metadata_json=draft.metadata,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_record(row)

    async def list(self, query: ConnectionListQuery) -> list[ConnectionRecord]:
        """Возвращает список подключений с учетом стандартных и кастомных фильтров.

        Нужен для демонстрации того, как репозиторий комбинирует базовые поля
        библиотеки с фильтрацией по проекту, владельцу и окружению.
        """

        statement = select(ProjectStoredConnection)
        if not query.include_deleted:
            statement = statement.where(ProjectStoredConnection.deleted_at.is_(None))
        if query.kind is not None:
            statement = statement.where(ProjectStoredConnection.kind == query.kind)
        if query.type is not None:
            statement = statement.where(ProjectStoredConnection.type == query.type)
        if query.name is not None:
            statement = statement.where(ProjectStoredConnection.name.contains(query.name))

        owner_id = query.extra_filters.get("owner_id")
        if owner_id is not None:
            statement = statement.where(ProjectStoredConnection.owner_id == str(owner_id))

        project_id = query.extra_filters.get("project_id")
        if project_id is not None:
            statement = statement.where(ProjectStoredConnection.project_id == int(project_id))

        environment = query.extra_filters.get("environment")
        if environment is not None:
            statement = statement.where(ProjectStoredConnection.environment == str(environment))

        rows = (await self._session.exec(statement)).all()
        return [self._to_record(row) for row in rows if self._matches_query(row, query)]

    async def get(self, connection_id: str) -> ConnectionRecord | None:
        """Получает одно подключение по идентификатору.

        Нужен, чтобы сервисный слой мог читать запись из пользовательского
        хранилища и дальше применять к ней политику доступа.
        """

        row = await self._session.get(ProjectStoredConnection, connection_id)
        return None if row is None else self._to_record(row)

    async def replace(self, connection_id: str, draft: ConnectionDraft) -> ConnectionRecord | None:
        """Полностью заменяет сохраненное подключение новыми данными.

        Нужен, чтобы показать реализацию update-операции в собственном
        репозитории и повторное шифрование секретов при изменении записи.
        """

        row = await self._session.get(ProjectStoredConnection, connection_id)
        if row is None:
            return None
        row.name = draft.name
        row.kind = draft.kind
        row.type = draft.type
        row.driver = draft.driver
        row.project_id = self._require_int_extra(draft.extra, "project_id")
        row.owner_id = self._require_str_extra(draft.extra, "owner_id")
        row.environment = self._require_str_extra(draft.extra, "environment")
        row.properties_json = draft.properties
        row.secrets_ciphertext = self._encryption_provider.encrypt(draft.secrets)
        row.labels_json = draft.labels
        row.metadata_json = draft.metadata
        row.updated_at = datetime.now(UTC)
        self._session.add(row)
        await self._session.flush()
        return self._to_record(row)

    async def delete(self, connection_id: str) -> ConnectionRecord | None:
        """Помечает подключение удаленным без физического удаления строки.

        Нужен примеру, чтобы продемонстрировать soft delete и совместимость с
        фильтрами `include_deleted` из доменной модели библиотеки.
        """

        row = await self._session.get(ProjectStoredConnection, connection_id)
        if row is None:
            return None
        row.deleted_at = datetime.now(UTC)
        row.updated_at = row.deleted_at
        self._session.add(row)
        await self._session.flush()
        return self._to_record(row)

    def _to_record(self, row: ProjectStoredConnection) -> ConnectionRecord:
        """Преобразует строку таблицы в доменную запись библиотеки.

        Это нужно, чтобы остальная часть системы работала с унифицированной
        моделью `ConnectionRecord`, не зная о деталях хранения.
        """

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
            extra={
                "project_id": row.project_id,
                "owner_id": row.owner_id,
                "environment": row.environment,
            },
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )

    def _matches_query(self, row: ProjectStoredConnection, query: ConnectionListQuery) -> bool:
        """Проверяет фильтры, которые неудобно выразить только SQL-запросом.

        Нужен, чтобы одинаково применять фильтрацию по `labels`, `metadata` и
        дополнительным полям, даже если они хранятся в JSON-структурах.
        """

        extra = {
            "project_id": row.project_id,
            "owner_id": row.owner_id,
            "environment": row.environment,
        }
        return (
            self._matches_mapping_filters(row.labels_json, query.label_filters)
            and self._matches_mapping_filters(row.metadata_json, query.metadata_filters)
            and self._matches_mapping_filters(extra, query.extra_filters)
        )

    def _matches_mapping_filters(
        self,
        values: dict[str, Any],
        filters: dict[str, Any],
    ) -> bool:
        """Сравнивает набор значений с ожидаемыми фильтрами по точному совпадению.

        Это небольшая вспомогательная функция, чтобы не дублировать одну и ту
        же логику проверки для разных словарей.
        """

        return all(values.get(key) == value for key, value in filters.items())

    def _require_int_extra(self, extra: dict[str, Any], key: str) -> int:
        """Извлекает обязательное целочисленное поле из `extra`.

        Нужен, чтобы кастомный репозиторий явно валидировал проектные поля,
        которые библиотека хранит в общем контейнере дополнительных данных.
        """

        value = extra.get(key)
        if value is None:
            raise ValidationFailedError(f"Custom repository requires '{key}' in extra fields.")
        return int(value)

    def _require_str_extra(self, extra: dict[str, Any], key: str) -> str:
        """Извлекает обязательное строковое поле из `extra`.

        Нужен по той же причине, что и `_require_int_extra`: пример должен
        гарантировать наличие прикладных полей до сохранения записи.
        """

        value = extra.get(key)
        if value is None:
            raise ValidationFailedError(f"Custom repository requires '{key}' in extra fields.")
        return str(value)


class ProjectConnectionUnitOfWork(ConnectionUnitOfWork):
    """UoW для демонстрационного репозитория, владеющий одной AsyncSession."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        encryption_provider: FernetEncryptionProvider,
    ) -> None:
        self._session = session
        self._connections = ProjectConnectionRepository(
            session,
            encryption_provider=encryption_provider,
        )

    @property
    def connections(self) -> ProjectConnectionRepository:
        return self._connections

    async def __aenter__(self) -> ProjectConnectionUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc is not None and self._session.in_transaction():
                await self.rollback()
        finally:
            await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class ProjectConnectionUnitOfWorkFactory(ConnectionUnitOfWorkFactory):
    """Фабрика request-scoped UoW для демонстрационного приложения."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        encryption_provider: FernetEncryptionProvider,
    ) -> None:
        self._session_factory = session_factory
        self._encryption_provider = encryption_provider

    def __call__(self) -> ProjectConnectionUnitOfWork:
        return ProjectConnectionUnitOfWork(
            self._session_factory(),
            encryption_provider=self._encryption_provider,
        )


class ProjectAccessPolicy:
    """Политика доступа, ограничивающая операции рамками владельца и проекта.

    Нужна примеру, чтобы показать, как библиотека встраивает прикладные правила
    авторизации в CRUD-операции и списки подключений.
    """

    async def scope_list(self, ctx: AccessContext, query: ConnectionListQuery) -> ConnectionListQuery:
        """Сужает выборку подключений до области видимости текущего актера.

        Это нужно, чтобы пользователь не мог запросить чужие подключения через
        общий список даже при ручной подстановке фильтров.
        """

        actor = self._require_actor(ctx)
        extra_filters = dict(query.extra_filters)
        extra_filters["owner_id"] = actor["owner_id"]
        if "project_id" in extra_filters and extra_filters["project_id"] not in actor["project_ids"]:
            raise AccessDeniedError("Requested project is not available for the current actor.")
        return query.model_copy(update={"extra_filters": extra_filters})

    async def can_create(self, ctx: AccessContext) -> None:
        """Проверяет право на создание подключения с указанными полями.

        Нужен, чтобы запретить создание подключений от имени другого владельца
        или для проекта вне разрешенной области.
        """

        actor = self._require_actor(ctx)
        payload = ctx.payload or {}
        self._ensure_payload_visible(actor, payload)

    async def can_get_one(self, ctx: AccessContext, connection: ConnectionRecord) -> None:
        """Проверяет доступ к конкретной сохраненной записи.

        Нужен, чтобы чтение одного подключения соблюдало те же ограничения, что
        и список, но уже на уровне найденной записи.
        """

        actor = self._require_actor(ctx)
        self._ensure_record_visible(actor, connection)

    async def can_update(
        self,
        ctx: AccessContext,
        connection: ConnectionRecord,
        patch: dict[str, Any],
    ) -> None:
        """Проверяет право на изменение записи и новых значений.

        Нужен, чтобы контролировать и сам доступ к подключению, и допустимость
        проектных полей после применения частичного обновления.
        """

        actor = self._require_actor(ctx)
        self._ensure_record_visible(actor, connection)
        merged_payload = dict(connection.extra)
        merged_payload.update(patch)
        self._ensure_payload_visible(actor, merged_payload)

    async def can_delete(self, ctx: AccessContext, connection: ConnectionRecord) -> None:
        """Проверяет право на удаление подключения.

        Нужен, чтобы soft delete нельзя было выполнить для записи вне текущей
        области видимости пользователя.
        """

        actor = self._require_actor(ctx)
        self._ensure_record_visible(actor, connection)

    def _require_actor(self, ctx: AccessContext) -> dict[str, Any]:
        """Возвращает актера в ожидаемом формате словаря.

        Нужен как защитный слой примера: политика явно требует контекст
        пользователя с `owner_id` и списком доступных проектов.
        """

        if not isinstance(ctx.actor, dict):
            raise AccessDeniedError("Actor is required.")
        return ctx.actor

    def _ensure_payload_visible(self, actor: dict[str, Any], payload: dict[str, Any]) -> None:
        """Проверяет, что входные данные относятся к разрешенному владельцу и проекту.

        Нужен для create/update-сценариев, где еще нет итоговой записи, но уже
        нужно валидировать область доступа по телу запроса.
        """

        if payload.get("owner_id") != actor["owner_id"]:
            raise AccessDeniedError("Actor cannot operate on another owner.")
        if payload.get("project_id") not in actor["project_ids"]:
            raise AccessDeniedError("Actor cannot operate on this project.")

    def _ensure_record_visible(self, actor: dict[str, Any], connection: ConnectionRecord) -> None:
        """Проверяет, что сохраненная запись видна текущему актеру.

        Нужен для read/update/delete-операций, где решение принимается по уже
        сохраненным значениям подключения.
        """

        if connection.extra.get("owner_id") != actor["owner_id"]:
            raise AccessDeniedError("Connection belongs to another owner.")
        if connection.extra.get("project_id") not in actor["project_ids"]:
            raise AccessDeniedError("Connection is outside the actor project scope.")


class ProjectErrorMapper(ErrorMapper):
    """Преобразует доменные ошибки в ответы HTTP API для демо-приложения.

    Нужен, чтобы показать настройку собственного контракта ошибок поверх
    стандартного поведения расширения `db_connection`.
    """

    def map_exception(self, exc: Exception) -> ErrorResponseSpec:
        """Переопределяет коды и сообщения ошибок для проектного API.

        В примере это нужно, чтобы скрывать от клиента отказы в доступе под
        видом `404` и выдавать более предметные коды ошибок.
        """

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
        spec = super().map_exception(exc)
        if spec.code == "connection_not_found":
            return ErrorResponseSpec(
                status_code=404,
                code="project_connection_not_found",
                message="Connection does not exist.",
                details=spec.details,
            )
        return spec


def get_actor(
    x_owner_id: str = Header(...),
    x_project_ids: str = Header(...),
) -> dict[str, Any]:
    """Собирает актера доступа из HTTP-заголовков.

    Нужен примеру, чтобы показать подключение пользовательской зависимости,
    которая передает в политику доступа контекст текущего запроса.
    """

    project_ids = {int(item.strip()) for item in x_project_ids.split(",") if item.strip()}
    return {
        "owner_id": x_owner_id,
        "project_ids": project_ids,
    }


async def _create_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)


def build_demo_extension() -> DBConnectionExtension:
    """Собирает настроенный экземпляр `DBConnectionExtension` для демо.

    Нужен как центральная точка конфигурации примера: здесь связываются
    репозиторий, политика доступа, схемы API, типы подключений и runtime.
    """

    encryption_provider = FernetEncryptionProvider(DEMO_FERNET_KEY)
    engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    run_async_blocking(_create_schema(engine))
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    uow_factory = ProjectConnectionUnitOfWorkFactory(
        session_factory,
        encryption_provider=encryption_provider,
    )
    return (
        DBConnectionExtension.builder()
        .with_uow_factory(uow_factory)
        .with_max_connections(25)
        .with_access_policy(ProjectAccessPolicy())
        .with_error_mapper(ProjectErrorMapper())
        .with_api_schemas(
            APISchemaSet(
                create=ProjectConnectionCreate,
                read=ProjectConnectionRead,
                update=ProjectConnectionUpdate,
            )
        )
        .with_actor_dependency(get_actor)
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
                public_model=HTTPAPIPublic,
                connector_factory=HTTPAPIConnector,
                capabilities={"check", "client", "request"},
                tags={"demo", "custom"},
            )
        )
        .build()
    )


app = FastAPI(title="db_connection demo", version="2.0.0")
extension = build_demo_extension()
extension.install(app, prefix="/db-connections")


@app.get("/")
def root() -> dict[str, Any]:
    """Возвращает краткое описание демо-приложения и полезные ссылки.

    Нужен как стартовая точка для ручного изучения примера без чтения исходного
    кода: из ответа видно, что именно демонстрирует приложение.
    """

    return {
        "message": "db_connection demo",
        "docs_url": "/docs",
        "db_connections_prefix": "/db-connections",
        "examples_url": "/demo/examples",
        "settings_url": "/demo/settings",
        "notes": [
            "Demo app uses a custom repository with explicit project fields.",
            "Access is scoped by x-owner-id and x-project-ids headers.",
            "ProjectErrorMapper hides access denials behind a 404.",
            "Custom type 'httpapi' is registered in the runtime registry.",
        ],
    }


@app.get("/demo/settings")
def get_demo_settings() -> dict[str, Any]:
    """Показывает текущие runtime-настройки расширения.

    Нужен, чтобы продемонстрировать, что настройки `DBConnectionExtension`
    доступны во время работы приложения и могут читаться через API.
    """

    return extension.runtime.settings.model_dump()


@app.post("/demo/settings/max-connections/{limit}")
def set_max_connections(limit: int) -> dict[str, Any]:
    """Обновляет лимит подключений в runtime-настройках демо.

    Нужен для демонстрации живого изменения настроек расширения без пересборки
    приложения и без ручной работы с внутренними объектами runtime.
    """

    return extension.update_settings(max_connections=limit).model_dump()


@app.get("/demo/examples")
def get_examples() -> dict[str, Any]:
    """Возвращает готовые примеры заголовков, payload и доступных маршрутов.

    Нужен, чтобы упростить ручное тестирование демо и сразу показать формат
    данных для встроенных и пользовательских типов подключений.
    """

    return {
        "headers": {
            "x-owner-id": "owner-1",
            "x-project-ids": "7,8",
        },
        "postgres_connection": {
            "name": "Warehouse",
            "kind": "sql",
            "type": "postgres",
            "project_id": 7,
            "owner_id": "owner-1",
            "environment": "prod",
            "properties": {
                "host": "postgres.internal",
                "port": 5432,
                "username": "analytics",
                "database": "warehouse",
                "secure": True,
            },
            "secrets": {
                "password": "change-me",
            },
            "labels": {
                "team": "bi",
            },
            "metadata": {
                "service": "superset",
            },
        },
        "custom_httpapi_connection": {
            "name": "Partner API",
            "kind": "service",
            "type": "httpapi",
            "project_id": 7,
            "owner_id": "owner-1",
            "environment": "stage",
            "properties": {
                "base_url": "https://api.partner.example",
                "health_path": "/ready",
                "timeout_seconds": 3,
            },
            "secrets": {
                "api_token": "demo-token",
            },
        },
        "available_endpoints": [
            "GET /db-connections/kinds",
            "GET /db-connections/types",
            "GET /db-connections",
            "POST /db-connections",
            "GET /db-connections/{connection_id}",
            "PATCH /db-connections/{connection_id}",
            "DELETE /db-connections/{connection_id}",
            "POST /db-connections/check",
            "POST /db-connections/{connection_id}/check",
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=3000)
