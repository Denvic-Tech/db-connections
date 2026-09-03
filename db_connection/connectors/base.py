from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from ..domain.entities import ConnectionCheckResult, ValidatedConnection

LOGGER = logging.getLogger("db_connection.connectors")


class Connector(ABC):
    @abstractmethod
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        raise NotImplementedError

    @abstractmethod
    async def get_client(self, connection: ValidatedConnection) -> Any:
        raise NotImplementedError

    def _log_check_exception(
        self,
        connection: ValidatedConnection,
        exc: BaseException,
    ) -> None:
        LOGGER.exception(
            "Connector '%s' check failed for connection '%s' (type='%s'): %s.",
            self.__class__.__name__,
            connection.name,
            connection.type,
            type(exc).__name__,
        )

    def _check_failure_result(
        self,
        connection: ValidatedConnection,
        exc: BaseException,
        *,
        message: str,
        exception: str | None = None,
    ) -> ConnectionCheckResult:
        self._log_check_exception(connection, exc)
        return ConnectionCheckResult(
            name=connection.name,
            connected=False,
            message=message,
            exception=exception,
        )
