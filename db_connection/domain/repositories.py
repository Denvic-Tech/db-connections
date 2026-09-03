from __future__ import annotations

from typing import Protocol

from .entities import ConnectionDraft, ConnectionListQuery, ConnectionRecord


class ConnectionRepository(Protocol):
    async def create(self, draft: ConnectionDraft) -> ConnectionRecord: ...

    async def list(self, query: ConnectionListQuery) -> list[ConnectionRecord]: ...

    async def get(self, connection_id: str) -> ConnectionRecord | None: ...

    async def replace(self, connection_id: str, draft: ConnectionDraft) -> ConnectionRecord | None: ...

    async def delete(self, connection_id: str) -> ConnectionRecord | None: ...
