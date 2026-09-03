from typing import Any

from kafka import KafkaProducer

from db_connection._async_utils import run_maybe_async
from db_connection.compat.models import DBConnection
from db_connection.compat.runtime_bridge import to_legacy_status, to_runtime_validated
from db_connection.compat.schemas import ConnectionStatus
from db_connection.connectors.kafka import KafkaConnector as RuntimeKafkaConnector

from .base import BaseConnector


class KafkaConnector(BaseConnector[KafkaProducer]):
    """Connector for Apache Kafka."""

    def __init__(self) -> None:
        self._runtime_connector = RuntimeKafkaConnector()

    def check(self, connection: DBConnection[KafkaProducer]) -> ConnectionStatus:
        try:
            return to_legacy_status(run_maybe_async(self._runtime_connector.check(to_runtime_validated(connection))))
        except Exception as error:
            return ConnectionStatus(
                name=connection.name,
                connected=False,
                message=str(error),
                exception=str(error),
            )

    def get_client(self, connection: DBConnection[KafkaProducer]) -> KafkaProducer | None:
        return run_maybe_async(self._runtime_connector.get_client(to_runtime_validated(connection)))

    def _build_config(self, connection: DBConnection[KafkaProducer]) -> dict[str, Any]:
        validated = to_runtime_validated(connection)
        return self._runtime_connector._build_config(validated)
