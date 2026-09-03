from __future__ import annotations

# pylint: disable=duplicate-code
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..domain.entities import ConnectionDraft, ConnectionListQuery, ConnectionRecord
from ..domain.repositories import ConnectionRepository
from ..infra.models import DefaultStoredConnection, ensure_stored_connection_table_model
from ..infra.record_mapper import StoredConnectionRecordMapper
from ..runtime.encryption import EncryptionProvider, NoOpEncryptionProvider


class DefaultSQLModelConnectionRepository(ConnectionRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        model_class: type[DefaultStoredConnection],
        encryption_provider: EncryptionProvider | None = None,
    ) -> None:
        self._session = session
        self._encryption_provider = encryption_provider or NoOpEncryptionProvider()
        self._model_class = ensure_stored_connection_table_model(model_class)
        self._record_mapper = StoredConnectionRecordMapper(encryption_provider=self._encryption_provider)

    async def create(self, draft: ConnectionDraft) -> ConnectionRecord:
        now = datetime.now(UTC)
        connection_id = str(uuid4())
        table = self._model_class.__table__
        statement = sa.insert(table).values(
            id=connection_id,
            name=draft.name,
            kind=draft.kind,
            type=draft.type,
            driver=draft.driver,
            driver_options_json=draft.driver_options,
            properties_json=draft.properties,
            secrets_ciphertext=self._encryption_provider.encrypt(draft.secrets),
            labels_json=draft.labels,
            metadata_json=draft.metadata,
            extra_json=draft.extra,
            created_at=now,
            updated_at=now,
        )
        await self._session.exec(statement)
        await self._session.flush()
        created = await self._fetch_row(connection_id)
        assert created is not None
        return self._to_record(created)

    async def list(self, query: ConnectionListQuery) -> list[ConnectionRecord]:
        table = self._model_class.__table__
        statement = select(*self._select_columns())
        if not query.include_deleted:
            statement = statement.where(table.c.deleted_at.is_(None))
        if query.kind is not None:
            statement = statement.where(table.c.kind == query.kind)
        if query.type is not None:
            statement = statement.where(table.c.type == query.type)
        if query.name is not None:
            statement = statement.where(table.c.name.contains(query.name))

        result = await self._session.execute(statement)
        records = [self._to_record(row) for row in result.mappings().all()]
        return [record for record in records if self._matches_filters(record, query)]

    async def get(self, connection_id: str) -> ConnectionRecord | None:
        row = await self._fetch_row(connection_id)
        return None if row is None else self._to_record(row)

    async def replace(self, connection_id: str, draft: ConnectionDraft) -> ConnectionRecord | None:
        existing = await self._fetch_row(connection_id)
        if existing is None:
            return None

        table = self._model_class.__table__
        statement = (
            sa.update(table)
            .where(table.c.id == connection_id)
            .values(
                name=draft.name,
                kind=draft.kind,
                type=draft.type,
                driver=draft.driver,
                driver_options_json=draft.driver_options,
                properties_json=draft.properties,
                secrets_ciphertext=self._encryption_provider.encrypt(draft.secrets),
                labels_json=draft.labels,
                metadata_json=draft.metadata,
                extra_json=draft.extra,
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.exec(statement)
        await self._session.flush()
        updated = await self._fetch_row(connection_id)
        assert updated is not None
        return self._to_record(updated)

    async def delete(self, connection_id: str) -> ConnectionRecord | None:
        existing = await self._fetch_row(connection_id)
        if existing is None:
            return None

        deleted_at = datetime.now(UTC)
        table = self._model_class.__table__
        statement = (
            sa.update(table)
            .where(table.c.id == connection_id)
            .values(
                deleted_at=deleted_at,
                updated_at=deleted_at,
            )
        )
        await self._session.exec(statement)
        await self._session.flush()
        deleted = await self._fetch_row(connection_id)
        assert deleted is not None
        return self._to_record(deleted)

    async def _fetch_row(self, connection_id: str) -> Mapping[str, Any] | None:
        table = self._model_class.__table__
        statement = select(*self._select_columns()).where(table.c.id == connection_id)
        result = await self._session.execute(statement)
        return result.mappings().first()

    def _select_columns(self) -> tuple[Any, ...]:
        table = self._model_class.__table__
        columns = [
            table.c.id,
            table.c.name,
            table.c.kind,
            table.c.type,
            table.c.driver,
            sa.type_coerce(table.c.driver_options_json, sa.JSON()).label("driver_options_json"),
            table.c.properties_json,
            table.c.secrets_ciphertext,
            table.c.labels_json,
            table.c.metadata_json,
            table.c.extra_json,
            table.c.created_at,
            table.c.updated_at,
            table.c.deleted_at,
        ]
        return tuple(columns)

    def _to_record(self, row: Mapping[str, Any]) -> ConnectionRecord:
        return self._record_mapper.to_record(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            type=row["type"],
            driver=row["driver"],
            driver_options_json=row.get("driver_options_json"),
            properties_json=row.get("properties_json"),
            secrets_ciphertext=row.get("secrets_ciphertext"),
            labels_json=row.get("labels_json"),
            metadata_json=row.get("metadata_json"),
            extra_json=row.get("extra_json"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )

    def _matches_filters(self, record: ConnectionRecord, query: ConnectionListQuery) -> bool:
        return (
            self._matches_mapping_filters(record.labels, query.label_filters)
            and self._matches_mapping_filters(record.metadata, query.metadata_filters)
            and self._matches_mapping_filters(record.extra, query.extra_filters)
        )

    def _matches_mapping_filters(
        self,
        values: dict[str, object],
        filters: dict[str, object],
    ) -> bool:
        return all(values.get(key) == value for key, value in filters.items())
