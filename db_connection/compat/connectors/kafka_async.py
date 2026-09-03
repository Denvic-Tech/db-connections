from typing import Any

from aiokafka import AIOKafkaProducer

from db_connection.compat.models import DBConnection
from db_connection.compat.runtime_bridge import to_legacy_status, to_runtime_validated
from db_connection.compat.schemas import ConnectionStatus
from db_connection.connectors.kafka import AsyncKafkaConnector as RuntimeAsyncKafkaConnector

from .base import AsyncBaseConnector


class AsyncKafkaConnector(AsyncBaseConnector[AIOKafkaProducer]):
    """Asynchronous connector for Apache Kafka using aiokafka."""

    def __init__(self) -> None:
        self._runtime_connector = RuntimeAsyncKafkaConnector()

    async def check(self, connection: DBConnection[AIOKafkaProducer]) -> ConnectionStatus:
        try:
            return to_legacy_status(await self._runtime_connector.check(to_runtime_validated(connection)))
        except Exception as error:
            return ConnectionStatus(
                name=connection.name,
                connected=False,
                message=str(error),
                exception=str(error),
            )

    async def get_client(self, connection: DBConnection[AIOKafkaProducer]) -> AIOKafkaProducer:
        return await self._runtime_connector.get_client(to_runtime_validated(connection))

    def _build_config(self, connection: DBConnection[AIOKafkaProducer]) -> dict[str, Any]:
        validated = to_runtime_validated(connection)
        return self._runtime_connector._build_config(validated)
