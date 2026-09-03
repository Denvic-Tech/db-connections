from typing import Any, TypeVar

from kafka import KafkaProducer
from sqlalchemy import Engine
from sqlmodel import select

from db_connection.compat import extension_config as ext_config
from db_connection.compat.connectors.base import BaseConnector
from db_connection.compat.models import DBConnection, DBConnection as DatabaseConnectionModel
from db_connection.compat.registry import CONNECTOR_REGISTRY
from db_connection.compat.schemas import ConnectionStatus
from db_connection.compat.types import ConnectionType

try:
    from botocore.client import BaseClient as S3BaseClient
except ImportError:  # pragma: no cover
    S3BaseClient = Any  # type: ignore[assignment]

TClient = TypeVar("TClient", Engine, KafkaProducer, S3BaseClient)


class ConnectionManager:
    ACTIVE_CONNECTIONS: int = None
    MAX_CONNECTIONS: int = None

    def __init__(self, dbconnection_model: type[DatabaseConnectionModel], max_connections: int):
        self.DBConnectionModel = dbconnection_model
        self.MAX_CONNECTIONS = max_connections

    @staticmethod
    def get_connector(conn_type: ConnectionType) -> BaseConnector[TClient]:
        connector = CONNECTOR_REGISTRY.get(conn_type)
        if connector is None:
            raise NotImplementedError(f"No connector for type: {conn_type}")

        return connector

    @staticmethod
    def check_connection(db_connection: DBConnection[TClient]) -> ConnectionStatus:
        connector = ConnectionManager.get_connector(db_connection.type)
        return connector.check(db_connection)

    @staticmethod
    def get_client(db_connection: DBConnection[TClient]) -> TClient | None:
        connector = ConnectionManager.get_connector(db_connection.type)
        return connector.get_client(db_connection)

    def get_db_connections(self, user, session, connection_type=None, filters=None):
        """
        Получить подключения с фильтрацией только по пользовательским полям.
        """
        statement = select(self.DBConnectionModel).where(
            self.DBConnectionModel.is_deleted == False
        )

        if connection_type is not None:
            statement = statement.where(self.DBConnectionModel.type == connection_type)

        if filters:
            filters_dict = filters.model_dump()
            for attr_name, attr_value in filters_dict.items():

                # Пропускаем None
                if attr_value is None:
                    continue
                # Если поле существует в модели - применяем фильтр
                if hasattr(self.DBConnectionModel, attr_name):
                    field = getattr(self.DBConnectionModel, attr_name)
                    statement = statement.where(field == attr_value)

        if ext_config.disable_pk_filtration(user):
            return session.exec(statement).all()

        if ext_config.USE_AUTH:
            statement = statement.where(
                *[
                    getattr(self.DBConnectionModel, fk) == getattr(user, pk)
                    for fk, pk in ext_config.db_connection_to_user_fks_mapping.items()
                ]
            )

        return session.exec(statement).all()

    def get_active_connections(self, user, session, connection_type=None) -> int:
        if not self.ACTIVE_CONNECTIONS:
            self.ACTIVE_CONNECTIONS = len(self.get_db_connections(user, session, connection_type))
        return self.ACTIVE_CONNECTIONS

    def validate_max_connections(self, user, session) -> bool:
        self.get_active_connections(user, session)
        # Считаем, что если MAX_CONNECTIONS==None, то нет лимита на кол-во подключений
        if self.MAX_CONNECTIONS is not None:
            return self.MAX_CONNECTIONS > self.ACTIVE_CONNECTIONS
        return True
