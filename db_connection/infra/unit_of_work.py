from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from ..application.uow import ConnectionUnitOfWork, ConnectionUnitOfWorkFactory
from ..infra.models import DefaultStoredConnection, ensure_stored_connection_table_model
from ..infra.repositories import DefaultSQLModelConnectionRepository
from ..runtime.encryption import EncryptionProvider, NoOpEncryptionProvider


class DefaultSQLModelConnectionUnitOfWork(ConnectionUnitOfWork):
    def __init__(
        self,
        session: AsyncSession,
        *,
        model_class: type[DefaultStoredConnection],
        encryption_provider: EncryptionProvider | None = None,
    ) -> None:
        self._session = session
        self._committed = False
        self._connections = DefaultSQLModelConnectionRepository(
            session,
            encryption_provider=encryption_provider,
            model_class=model_class,
        )

    @property
    def connections(self) -> DefaultSQLModelConnectionRepository:
        return self._connections

    async def __aenter__(self) -> DefaultSQLModelConnectionUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc is not None and self._session.in_transaction():
                await self.rollback()
        finally:
            await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        await self._session.rollback()


class DefaultSQLModelConnectionUnitOfWorkFactory(ConnectionUnitOfWorkFactory):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        model_class: type[DefaultStoredConnection],
        encryption_provider: EncryptionProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._encryption_provider = encryption_provider or NoOpEncryptionProvider()
        self._model_class = ensure_stored_connection_table_model(model_class)

    def __call__(self) -> DefaultSQLModelConnectionUnitOfWork:
        return DefaultSQLModelConnectionUnitOfWork(
            self._session_factory(),
            encryption_provider=self._encryption_provider,
            model_class=self._model_class,
        )


__all__ = [
    "DefaultSQLModelConnectionUnitOfWork",
    "DefaultSQLModelConnectionUnitOfWorkFactory",
]
