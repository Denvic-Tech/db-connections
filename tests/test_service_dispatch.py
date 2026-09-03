from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel

from db_connection import (
    AllowAllAccessPolicy,
    ConnectionCheckResult,
    ConnectionDraft,
    ConnectionListQuery,
    ConnectionPatch,
    ConnectionRecord,
    ConnectionRegistry,
    ConnectionUnitOfWork,
    ConnectionUnitOfWorkFactory,
    Connector,
    DBConnectionSettings,
    KindSpec,
    StoredConnectionIssue,
    TypeSpec,
    ValidationFailedError,
)
from db_connection.application.service import ConnectionService


class FakeProperties(BaseModel):
    value: str


class FakeSecrets(BaseModel):
    token: str


class FakeSyncConnector(Connector):
    def check(self, connection) -> ConnectionCheckResult:
        return ConnectionCheckResult(name=connection.name, connected=True, message=connection.properties.value)

    def get_client(self, connection) -> str:
        return f"sync:{connection.properties.value}"


class FakeAsyncConnector(Connector):
    async def check(self, connection) -> ConnectionCheckResult:
        return ConnectionCheckResult(name=connection.name, connected=True, message=connection.properties.value)

    async def get_client(self, connection) -> str:
        return f"async:{connection.properties.value}"


@dataclass
class InMemoryRepository:
    records: dict[str, ConnectionRecord]

    def create(self, draft: ConnectionDraft) -> ConnectionRecord:
        now = datetime.now(UTC)
        record = ConnectionRecord(
            id=str(uuid4()),
            name=draft.name,
            kind=draft.kind,
            type=draft.type,
            driver=draft.driver,
            properties=draft.properties,
            secrets=draft.secrets,
            labels=draft.labels,
            metadata=draft.metadata,
            extra=draft.extra,
            created_at=now,
            updated_at=now,
        )
        self.records[record.id] = record
        return record

    def list(self, query: ConnectionListQuery) -> list[ConnectionRecord]:
        return list(self.records.values())

    def get(self, connection_id: str) -> ConnectionRecord | None:
        return self.records.get(connection_id)

    def replace(self, connection_id: str, draft: ConnectionDraft) -> ConnectionRecord | None:
        existing = self.records.get(connection_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            name=draft.name,
            driver=draft.driver,
            properties=draft.properties,
            secrets=draft.secrets,
            labels=draft.labels,
            metadata=draft.metadata,
            extra=draft.extra,
            updated_at=datetime.now(UTC),
        )
        self.records[connection_id] = updated
        return updated

    def delete(self, connection_id: str) -> ConnectionRecord | None:
        existing = self.records.get(connection_id)
        if existing is None:
            return None
        deleted = replace(
            existing,
            deleted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.records[connection_id] = deleted
        return deleted


class InMemoryUnitOfWork(ConnectionUnitOfWork):
    def __init__(self, repository: InMemoryRepository, counter: list[str] | None = None) -> None:
        self._repository = repository
        self._counter = counter if counter is not None else []

    @property
    def connections(self) -> InMemoryRepository:
        return self._repository

    async def __aenter__(self) -> InMemoryUnitOfWork:
        self._counter.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._counter.append("exit")

    async def commit(self) -> None:
        self._counter.append("commit")

    async def rollback(self) -> None:
        self._counter.append("rollback")


class InMemoryUnitOfWorkFactory(ConnectionUnitOfWorkFactory):
    def __init__(self, repository: InMemoryRepository, counter: list[str] | None = None) -> None:
        self._repository = repository
        self._counter = counter if counter is not None else []

    def __call__(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self._repository, self._counter)


class RecordingOwnershipResolver:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, object]] = []
        self.patch_calls: list[tuple[str, object]] = []

    async def resolve_create(self, ctx, draft: ConnectionDraft) -> ConnectionDraft:
        self.create_calls.append((ctx.operation, ctx.actor))
        extra = dict(draft.extra)
        extra["owner_id"] = _actor_owner_id(ctx.actor)
        return replace(draft, extra=extra)

    async def resolve_patch(self, ctx, existing: ConnectionRecord, patch: ConnectionPatch) -> ConnectionPatch:
        self.patch_calls.append((ctx.operation, ctx.actor))
        extra = dict(existing.extra)
        extra.update({} if patch.extra is None else dict(patch.extra))
        extra["owner_id"] = _actor_owner_id(ctx.actor)
        return ConnectionPatch(extra=extra)


def _actor_owner_id(actor: object) -> str:
    if isinstance(actor, dict):
        return actor["owner_id"]
    return actor.owner_id


def build_service(
    connector_factory=FakeAsyncConnector,
    *,
    repository: InMemoryRepository | None = None,
    counter: list[str] | None = None,
    ownership_resolver=None,
    secrets_model: type[BaseModel] | None = None,
) -> ConnectionService:
    registry = ConnectionRegistry()
    registry.register_kind(KindSpec(name="custom"))
    registry.register_type(
        TypeSpec(
            name="fake",
            kind="custom",
            properties_model=FakeProperties,
            secrets_model=secrets_model,
            public_model=FakeProperties,
            connector_factory=connector_factory,
        )
    )
    repo = repository or InMemoryRepository(records={})
    return ConnectionService(
        settings=DBConnectionSettings(),
        registry=registry,
        uow_factory=InMemoryUnitOfWorkFactory(repo, counter),
        access_policy=AllowAllAccessPolicy(),
        ownership_resolver=ownership_resolver,
    )


@pytest.mark.asyncio
async def test_sync_connector_dispatch() -> None:
    service = build_service(connector_factory=FakeSyncConnector)
    result = await service.check_payload(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "sync-ok"},
        )
    )
    assert result.connected is True
    assert result.message == "sync-ok"


@pytest.mark.asyncio
async def test_async_connector_dispatch() -> None:
    service = build_service()
    result = await service.check_payload(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "async-ok"},
        )
    )
    assert result.connected is True
    assert result.message == "async-ok"


@pytest.mark.asyncio
async def test_create_commits_once_when_service_owns_uow() -> None:
    counter: list[str] = []
    service = build_service(counter=counter)

    await service.create(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "created"},
        )
    )

    assert counter.count("commit") == 1
    assert counter.count("enter") == 1
    assert counter.count("exit") == 1


@pytest.mark.asyncio
async def test_create_skips_commit_when_uow_is_provided() -> None:
    counter: list[str] = []
    repository = InMemoryRepository(records={})
    service = build_service(repository=repository, counter=counter)
    uow = InMemoryUnitOfWork(repository, counter)

    await service.create(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "created"},
        ),
        uow=uow,
    )

    assert counter.count("commit") == 0
    assert counter.count("enter") == 0
    assert counter.count("exit") == 0


@pytest.mark.asyncio
async def test_create_uses_ownership_resolver_before_persisting() -> None:
    resolver = RecordingOwnershipResolver()
    service = build_service(ownership_resolver=resolver)

    record = await service.create(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "created"},
        ),
        actor={"owner_id": "owner-create"},
    )

    assert resolver.create_calls == [("create", {"owner_id": "owner-create"})]
    assert record.extra["owner_id"] == "owner-create"


@pytest.mark.asyncio
async def test_update_uses_resolved_patch_before_persisting() -> None:
    resolver = RecordingOwnershipResolver()
    repository = InMemoryRepository(records={})
    created = repository.create(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "created"},
            extra={"owner_id": "owner-initial", "scope": "shared"},
        )
    )
    service = build_service(repository=repository, ownership_resolver=resolver)

    updated = await service.update(
        created.id,
        ConnectionPatch(extra={"scope": "archived"}),
        actor={"owner_id": "owner-update"},
    )

    assert resolver.patch_calls == [("update", {"owner_id": "owner-update"})]
    assert updated.extra == {"owner_id": "owner-update", "scope": "archived"}


@pytest.mark.asyncio
async def test_check_payload_uses_ownership_resolver_actor() -> None:
    resolver = RecordingOwnershipResolver()
    service = build_service(ownership_resolver=resolver)

    result = await service.check_payload(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "checked"},
        ),
        actor={"owner_id": "owner-check"},
    )

    assert result.connected is True
    assert resolver.create_calls == [("check_payload", {"owner_id": "owner-check"})]


@pytest.mark.asyncio
async def test_check_stored_uses_patch_resolver_actor() -> None:
    resolver = RecordingOwnershipResolver()
    repository = InMemoryRepository(records={})
    created = repository.create(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "created"},
            extra={"owner_id": "owner-initial", "scope": "shared"},
        )
    )
    service = build_service(repository=repository, ownership_resolver=resolver)

    result = await service.check_stored(
        created.id,
        actor={"owner_id": "owner-stored"},
        patch=ConnectionPatch(extra={"scope": "validated"}),
    )

    assert result.connected is True
    assert resolver.patch_calls == [("check_stored", {"owner_id": "owner-stored"})]


@pytest.mark.asyncio
async def test_check_stored_requires_secret_repair_when_stored_secrets_are_unreadable() -> None:
    repository = InMemoryRepository(records={})
    created = repository.create(
        ConnectionDraft(
            name="fake",
            kind="custom",
            type="fake",
            properties={"value": "created"},
            secrets={"token": "secret"},
        )
    )
    repository.records[created.id] = replace(
        created,
        secrets={},
        read_issues=[
            StoredConnectionIssue(
                field="secrets",
                code="unreadable_secrets",
                message="Stored connection secrets could not be decrypted.",
            )
        ],
    )
    service = build_service(repository=repository, secrets_model=FakeSecrets)

    with pytest.raises(ValidationFailedError) as exc_info:
        await service.check_stored(created.id)

    assert exc_info.value.details == {"repair_required": ["secrets"]}


@pytest.mark.asyncio
async def test_get_client_requires_secret_repair_when_stored_secrets_are_unreadable() -> None:
    service = build_service(secrets_model=FakeSecrets)
    record = ConnectionRecord(
        id="record-1",
        name="fake",
        kind="custom",
        type="fake",
        properties={"value": "created"},
        secrets={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        read_issues=[
            StoredConnectionIssue(
                field="secrets",
                code="unreadable_secrets",
                message="Stored connection secrets could not be decrypted.",
            )
        ],
    )

    with pytest.raises(ValidationFailedError) as exc_info:
        await service.get_client(record)

    assert exc_info.value.details == {"repair_required": ["secrets"]}
