from __future__ import annotations

from typing import Protocol

from ..domain.entities import ConnectionDraft, ConnectionPatch, ConnectionRecord
from .policies import AccessContext


class ConnectionOwnershipResolver(Protocol):
    async def resolve_create(
        self,
        ctx: AccessContext,
        draft: ConnectionDraft,
    ) -> ConnectionDraft: ...

    async def resolve_patch(
        self,
        ctx: AccessContext,
        existing: ConnectionRecord,
        patch: ConnectionPatch,
    ) -> ConnectionPatch: ...


class NoOpConnectionOwnershipResolver:
    async def resolve_create(
        self,
        ctx: AccessContext,  # noqa: ARG002
        draft: ConnectionDraft,
    ) -> ConnectionDraft:
        return draft

    async def resolve_patch(
        self,
        ctx: AccessContext,  # noqa: ARG002
        existing: ConnectionRecord,  # noqa: ARG002
        patch: ConnectionPatch,
    ) -> ConnectionPatch:
        return patch
