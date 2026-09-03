from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from db_connection.compat import exceptions as exc, types
from db_connection.compat.models import DBConnection
from db_connection.compat.runtime_bridge import to_legacy_status, to_runtime_validated
from db_connection.compat.schemas import ConnectionStatus
from db_connection.connectors.sql import SQLConnector as RuntimeSQLConnector

from .base import AsyncBaseConnector

ASYNC_SQL_CONNECTION_TYPES = {
    types.ConnectionType.POSTGRES,
    types.ConnectionType.MYSQL,
    types.ConnectionType.MSSQL,
}


class AsyncSQLConnector(AsyncBaseConnector[AsyncEngine]):
    """Asynchronous connector for all SQLAlchemy-compatible databases."""

    def __init__(self) -> None:
        self._runtime_connector = RuntimeSQLConnector(preferred_mode="async")

    def build_connection_url(self, db_conn: DBConnection[AsyncEngine]) -> URL | str:
        if db_conn.type not in ASYNC_SQL_CONNECTION_TYPES:
            raise exc.DBTypeNotSupported(
                type_received=db_conn.type,
                message="Async version not supported",
            )
        return self._runtime_connector.build_connection_url(to_runtime_validated(db_conn, mode="async"))

    async def check(self, connection: DBConnection[AsyncEngine]) -> ConnectionStatus:
        try:
            return to_legacy_status(
                await self._runtime_connector.check(to_runtime_validated(connection, mode="async"))
            )
        except exc.DBTypeNotSupported:
            raise
        except Exception as error:
            return ConnectionStatus(
                name=connection.name,
                connected=False,
                message=str(error),
                exception=str(error),
            )

    async def get_client(self, connection: DBConnection[AsyncEngine]) -> AsyncEngine | None:
        try:
            return await self._runtime_connector.get_client(to_runtime_validated(connection, mode="async"))
        except Exception:
            return None
