from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from db_connection.compat.models import DBConnection
from db_connection.compat.schemas import ConnectionStatus  # <-- Переименуем DBConnectionStatus

TClient = TypeVar("TClient")


class AsyncBaseConnector(ABC, Generic[TClient]):
    @abstractmethod
    async def check(self, connection: DBConnection[TClient]) -> ConnectionStatus:
        """
        Checks the health of the connection.

        :param connection: The connection configuration object.
        :return: A ConnectionStatus object.
        """
        ...

    @abstractmethod
    async def get_client(self, connection: DBConnection[TClient]) -> TClient | None:
        """
        Yields a client instance for the connection.

        The type of the client depends on the connector implementation
        (e.g., SQLAlchemy Engine, KafkaProducer).

        :param connection: The connection configuration object.
        """
        ...


class BaseConnector(ABC, Generic[TClient]):
    """Abstract base class for connection handlers."""

    @abstractmethod
    def check(self, connection: DBConnection[TClient]) -> ConnectionStatus:
        """
        Checks the health of the connection.

        :param connection: The connection configuration object.
        :return: A ConnectionStatus object.
        """
        ...

    @abstractmethod
    def get_client(self, connection: DBConnection[TClient]) -> TClient | None:
        """
        Yields a client instance for the connection.

        The type of the client depends on the connector implementation
        (e.g., SQLAlchemy Engine, KafkaProducer).

        :param connection: The connection configuration object.
        """
        ...
