from __future__ import annotations

from typing import TYPE_CHECKING, Any

from db_connection._async_utils import run_maybe_async
from db_connection.compat.models import DBConnection
from db_connection.compat.runtime_bridge import to_legacy_status, to_runtime_validated
from db_connection.compat.schemas import ConnectionStatus
from db_connection.connectors.s3 import S3Connector as RuntimeS3Connector

from .base import BaseConnector

if TYPE_CHECKING:  # pragma: no cover
    from botocore.client import BaseClient
else:  # Fallback type to keep typing happy if botocore is missing
    BaseClient = Any  # type: ignore[misc,assignment]


class S3Connector(BaseConnector[BaseClient]):
    """Коннектор для S3-совместимых хранилищ (sync)."""

    def __init__(self) -> None:
        self._runtime_connector = RuntimeS3Connector()

    def check(self, connection: DBConnection[BaseClient]) -> ConnectionStatus:
        try:
            return to_legacy_status(
                run_maybe_async(self._runtime_connector.check(to_runtime_validated(connection)))
            )
        except Exception as error:  # pragma: no cover - safeguard
            return ConnectionStatus(
                name=connection.name,
                connected=False,
                message=str(error),
                exception=str(error),
            )

    def get_client(self, connection: DBConnection[BaseClient]) -> BaseClient | None:
        try:
            return run_maybe_async(self._runtime_connector.get_client(to_runtime_validated(connection)))
        except Exception:
            return None
