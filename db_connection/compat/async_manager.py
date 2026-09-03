from typing import TypeVar

from aiokafka import AIOKafkaProducer
from sqlalchemy.ext.asyncio import AsyncEngine

from db_connection.compat.async_registry import ASYNC_CONNECTOR_REGISTRY
from db_connection.compat.connectors.base import AsyncBaseConnector
from db_connection.compat.models import DBConnection
from db_connection.compat.schemas import ConnectionStatus
from db_connection.compat.types import ConnectionType

TClient = TypeVar("TClient", AsyncEngine, AIOKafkaProducer)


class AsyncConnectionManager:

    @staticmethod
    async def get_connector(conn_type: ConnectionType) -> AsyncBaseConnector[TClient]:
        """Finds the appropriate connector for the given connection type."""
        connector = ASYNC_CONNECTOR_REGISTRY.get(conn_type)
        if not connector:
            raise NotImplementedError(f"No connector implemented for type: {conn_type}")

        return connector

    @staticmethod
    async def check_connection(db_connection: DBConnection[TClient]) -> ConnectionStatus:
        """
        Checks the connection by dispatching to the appropriate connector.
        """
        connector = await AsyncConnectionManager.get_connector(db_connection.type)
        return await connector.check(db_connection)

    @staticmethod
    async def get_client(db_connection: DBConnection[TClient]) -> TClient | None:
        """
        Gets a client by dispatching to the appropriate connector.
        """
        connector = await AsyncConnectionManager.get_connector(db_connection.type)
        return await connector.get_client(db_connection)
