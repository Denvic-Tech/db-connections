from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..domain.repositories import ConnectionRepository


class ConnectionUnitOfWork(Protocol):
    @property
    def connections(self) -> ConnectionRepository: ...

    async def __aenter__(self) -> ConnectionUnitOfWork: ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class ConnectionUnitOfWorkFactory(Protocol):
    def __call__(self) -> ConnectionUnitOfWork: ...


ConnectionUnitOfWorkDependency = Callable[..., ConnectionUnitOfWork]


__all__ = [
    "ConnectionUnitOfWork",
    "ConnectionUnitOfWorkDependency",
    "ConnectionUnitOfWorkFactory",
]
