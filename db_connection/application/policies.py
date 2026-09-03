from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..domain.entities import ConnectionDraft, ConnectionListQuery, ConnectionPatch, ConnectionRecord


@dataclass(slots=True)
class AccessContext:
    actor: Any
    operation: str
    connection_id: str | None = None
    payload: dict[str, Any] | None = None


class AccessPolicy(Protocol):
    async def scope_list(self, ctx: AccessContext, query: ConnectionListQuery) -> ConnectionListQuery: ...

    async def can_create(self, ctx: AccessContext, draft: ConnectionDraft) -> None: ...

    async def can_get_one(self, ctx: AccessContext, existing: ConnectionRecord) -> None: ...

    async def can_update(
        self,
        ctx: AccessContext,
        existing: ConnectionRecord,
        patch: ConnectionPatch,
    ) -> None: ...

    async def can_delete(self, ctx: AccessContext, existing: ConnectionRecord) -> None: ...


class AllowAllAccessPolicy:
    async def scope_list(self, ctx: AccessContext, query: ConnectionListQuery) -> ConnectionListQuery: # noqa: ARG002
        return query

    async def can_create(self, ctx: AccessContext, draft: ConnectionDraft) -> None: # noqa: ARG002
        return None

    async def can_get_one(self, ctx: AccessContext, existing: ConnectionRecord) -> None: # noqa: ARG002
        return None

    async def can_update(
        self,
        ctx: AccessContext,  # noqa: ARG002
        existing: ConnectionRecord, # noqa: ARG002
        patch: ConnectionPatch, # noqa: ARG002
    ) -> None:
        return None

    async def can_delete(self, ctx: AccessContext, existing: ConnectionRecord) -> None: # noqa: ARG002
        return None
