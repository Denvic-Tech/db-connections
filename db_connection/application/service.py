from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from .._async_utils import maybe_await
from ..application.ownership import ConnectionOwnershipResolver, NoOpConnectionOwnershipResolver
from ..application.policies import AccessContext, AccessPolicy
from ..application.public_projection import (
    BrokenPublicConnectionView,
    ConnectionPublicProjector,
    PublicConnectionView,
)
from ..application.uow import ConnectionUnitOfWork, ConnectionUnitOfWorkFactory
from ..application.validation import ValidationService
from ..connectors.base import Connector
from ..domain import patch_to_dict
from ..domain.entities import (
    ConnectionCheckResult,
    ConnectionDraft,
    ConnectionListQuery,
    ConnectionPatch,
    ConnectionRecord,
    patch_fields_set,
)
from ..domain.specs import KindSpec, TypeSpec
from ..errors import (
    ConnectionLimitExceededError,
    ConnectionNotFoundError,
    ValidationFailedError,
)
from ..registry.base import ConnectionRegistry

if TYPE_CHECKING:
    from db_connection.runtime.settings import DBConnectionSettings


class ConnectionService:
    def __init__(
        self,
        *,
        settings: DBConnectionSettings,
        registry: ConnectionRegistry,
        uow_factory: ConnectionUnitOfWorkFactory,
        access_policy: AccessPolicy,
        ownership_resolver: ConnectionOwnershipResolver | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._uow_factory = uow_factory
        self._access_policy = access_policy
        self._ownership_resolver = ownership_resolver or NoOpConnectionOwnershipResolver()
        self._validation = ValidationService(registry)
        self._public_projector = ConnectionPublicProjector(registry)

    def list_kinds(self) -> list[KindSpec]:
        return self._registry.list_kinds()

    def list_types(self) -> list[TypeSpec]:
        return self._registry.list_types()

    async def create(
        self,
        payload: ConnectionDraft,
        actor: Any = None,
        *,
        uow: ConnectionUnitOfWork | None = None,
    ) -> ConnectionRecord:
        initial_ctx = AccessContext(
            actor=actor,
            operation="create",
            payload=self._payload_with_extra(asdict(payload)),
        )
        resolved_payload = await maybe_await(self._ownership_resolver.resolve_create(ctx=initial_ctx, draft=payload))
        ctx = AccessContext(
            actor=actor,
            operation="create",
            payload=self._payload_with_extra(asdict(resolved_payload)),
        )
        can_create = self._access_policy.can_create
        if len(inspect.signature(can_create).parameters) == 1:
            await maybe_await(can_create(ctx))
        else:
            await maybe_await(can_create(ctx, resolved_payload))
        validated = self._validation.validate(resolved_payload)

        async with self._use_uow(uow) as (active_uow, should_commit):
            if self._settings.max_connections is not None:
                active = len(await maybe_await(active_uow.connections.list(ConnectionListQuery())))
                if active >= self._settings.max_connections:
                    raise ConnectionLimitExceededError(self._settings.max_connections)

            record = await maybe_await(
                active_uow.connections.create(self._to_persisted_draft(resolved_payload, validated))
            )
            if should_commit:
                await maybe_await(active_uow.commit())
            return record

    async def list(
        self,
        query: ConnectionListQuery,
        actor: Any = None,
        *,
        uow: ConnectionUnitOfWork | None = None,
    ) -> list[ConnectionRecord]:
        scoped = await maybe_await(
            self._access_policy.scope_list(
                AccessContext(actor=actor, operation="list"),
                query,
            )
        )
        async with self._use_uow(uow) as (active_uow, _):
            return await maybe_await(active_uow.connections.list(scoped))

    async def get(
        self,
        connection_id: str,
        actor: Any = None,
        *,
        uow: ConnectionUnitOfWork | None = None,
    ) -> ConnectionRecord:
        async with self._use_uow(uow) as (active_uow, _):
            record = await maybe_await(active_uow.connections.get(connection_id))
            if record is None or record.deleted_at is not None:
                raise ConnectionNotFoundError(connection_id)
            await maybe_await(
                self._access_policy.can_get_one(
                    AccessContext(actor=actor, operation="get", connection_id=connection_id),
                    record,
                )
            )
            return record

    async def update(
        self,
        connection_id: str,
        patch: ConnectionPatch,
        actor: Any = None,
        *,
        uow: ConnectionUnitOfWork | None = None,
    ) -> ConnectionRecord:
        async with self._use_uow(uow) as (active_uow, should_commit):
            existing = await self.get(connection_id, actor=actor, uow=active_uow)
            initial_ctx = AccessContext(
                actor=actor,
                operation="update",
                connection_id=connection_id,
                payload=self._payload_with_extra(patch_to_dict(patch)),
            )
            resolved_patch = await maybe_await(
                self._ownership_resolver.resolve_patch(
                    ctx=initial_ctx,
                    existing=existing,
                    patch=patch,
                )
            )
            await maybe_await(
                self._access_policy.can_update(
                    AccessContext(
                        actor=actor,
                        operation="update",
                        connection_id=connection_id,
                        payload=self._payload_with_extra(patch_to_dict(resolved_patch)),
                    ),
                    existing,
                    resolved_patch,
                )
            )
            self._ensure_patch_can_replace_unreadable_secrets(existing, resolved_patch)
            merged = self._merge(existing, resolved_patch)
            validated = self._validation.validate(merged)

            updated = await maybe_await(
                active_uow.connections.replace(
                    connection_id,
                    self._to_persisted_draft(merged, validated),
                )
            )
            if updated is None:
                raise ConnectionNotFoundError(connection_id)
            if should_commit:
                await maybe_await(active_uow.commit())
            return updated

    async def delete(
        self,
        connection_id: str,
        actor: Any = None,
        *,
        uow: ConnectionUnitOfWork | None = None,
    ) -> ConnectionRecord:
        async with self._use_uow(uow) as (active_uow, should_commit):
            existing = await self.get(connection_id, actor=actor, uow=active_uow)
            await maybe_await(
                self._access_policy.can_delete(
                    AccessContext(actor=actor, operation="delete", connection_id=connection_id),
                    existing,
                )
            )
            deleted = await maybe_await(active_uow.connections.delete(connection_id))
            if deleted is None:
                raise ConnectionNotFoundError(connection_id)
            if should_commit:
                await maybe_await(active_uow.commit())
            return deleted

    async def check_payload(self, payload: ConnectionDraft, actor: Any = None) -> ConnectionCheckResult:
        ctx = AccessContext(
            actor=actor,
            operation="check_payload",
            payload=self._payload_with_extra(asdict(payload)),
        )
        resolved_payload = await maybe_await(self._ownership_resolver.resolve_create(ctx=ctx, draft=payload))
        validated = self._validation.validate(resolved_payload)
        return await maybe_await(self._get_connector(validated.type).check(validated))

    async def check_stored(
        self,
        connection_id: str,
        actor: Any = None,
        patch: ConnectionPatch | None = None,
        *,
        uow: ConnectionUnitOfWork | None = None,
    ) -> ConnectionCheckResult:
        async with self._use_uow(uow) as (active_uow, _):
            record = await self.get(connection_id, actor=actor, uow=active_uow)
            draft = record
            if patch is not None:
                resolved_patch = await maybe_await(
                    self._ownership_resolver.resolve_patch(
                        ctx=AccessContext(
                            actor=actor,
                            operation="check_stored",
                            connection_id=connection_id,
                            payload=self._payload_with_extra(patch_to_dict(patch)),
                        ),
                        existing=record,
                        patch=patch,
                    )
                )
                self._ensure_patch_can_replace_unreadable_secrets(record, resolved_patch)
                draft = self._merge(record, resolved_patch)
            else:
                self._ensure_readable_secrets(record)
            validated = self._validation.validate(draft)
            return await maybe_await(self._get_connector(validated.type).check(validated))

    def build_public_view(self, record: ConnectionRecord) -> PublicConnectionView:
        return self._public_projector.build(record)

    def build_read_view(self, record: ConnectionRecord) -> PublicConnectionView | BrokenPublicConnectionView:
        return self._public_projector.build_any(record)

    async def get_client(self, record_or_draft: ConnectionRecord | ConnectionDraft) -> Any:
        if isinstance(record_or_draft, ConnectionRecord):
            self._ensure_readable_secrets(record_or_draft)
        validated = self._validation.validate(record_or_draft)
        connector = self._get_connector(validated.type)
        return await connector.get_client(validated)

    def _merge(self, existing: ConnectionRecord, patch: ConnectionPatch) -> ConnectionDraft:
        patch_data = patch_to_dict(patch)
        if "kind" in patch_data or "type" in patch_data:
            raise ValidationFailedError("Changing connection kind or type is not supported.")

        patch_fields = patch_fields_set(patch)
        return ConnectionDraft(
            name=patch.name if "name" in patch_fields else existing.name,
            kind=existing.kind,
            type=existing.type,
            driver=patch.driver if "driver" in patch_fields else existing.driver,
            driver_options=patch.driver_options if "driver_options" in patch_fields else existing.driver_options,
            properties=patch.properties if "properties" in patch_fields else existing.properties,
            secrets=patch.secrets if "secrets" in patch_fields else existing.secrets,
            labels=patch.labels if "labels" in patch_fields else existing.labels,
            metadata=patch.metadata if "metadata" in patch_fields else existing.metadata,
            extra=patch.extra if "extra" in patch_fields else existing.extra,
        )

    def _get_connector(self, connection_type: str) -> Connector:
        spec = self._registry.get_type(connection_type)
        if spec.connector_factory is None:
            raise ValidationFailedError(f"Connector is not configured for '{connection_type}'.")
        return spec.connector_factory()

    def _to_persisted_draft(
        self,
        source: ConnectionDraft | ConnectionRecord,
        validated,
    ) -> ConnectionDraft:
        return ConnectionDraft(
            name=source.name,
            kind=source.kind,
            type=source.type,
            driver=source.driver,
            driver_options=validated.driver_options,
            properties=validated.properties.model_dump(mode="json"),
            secrets={} if validated.secrets is None else validated.secrets.model_dump(mode="json"),
            labels=dict(source.labels),
            metadata=dict(source.metadata),
            extra=dict(source.extra),
        )

    def _payload_with_extra(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        extra = data.pop("extra", None) or {}
        if isinstance(extra, dict):
            data.update(extra)
        return data

    def _ensure_readable_secrets(self, record: ConnectionRecord) -> None:
        if record.has_read_issue("unreadable_secrets", field_name="secrets"):
            self._raise_repair_required_error()

    def _ensure_patch_can_replace_unreadable_secrets(
        self,
        record: ConnectionRecord,
        patch: ConnectionPatch,
    ) -> None:
        if record.has_read_issue("unreadable_secrets", field_name="secrets") and "secrets" not in patch_fields_set(
            patch
        ):
            self._raise_repair_required_error()

    def _raise_repair_required_error(self) -> None:
        raise ValidationFailedError(
            "Stored connection secrets cannot be read. Provide a replacement 'secrets' payload to repair the connection.",
            details={"repair_required": ["secrets"]},
        )

    @asynccontextmanager
    async def _use_uow(
        self,
        uow: ConnectionUnitOfWork | None,
    ):
        if uow is not None:
            yield uow, False
            return

        async with self._uow_factory() as managed_uow:
            yield managed_uow, True
