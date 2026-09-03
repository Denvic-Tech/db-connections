from db_connection.compat.connectors.base import AsyncBaseConnector
from db_connection.compat.connectors.kafka_async import AsyncKafkaConnector
from db_connection.compat.connectors.sql_async import AsyncSQLConnector
from db_connection.compat.types import ConnectionType

ASYNC_CONNECTOR_REGISTRY: dict[ConnectionType, AsyncBaseConnector] = {
    ConnectionType.POSTGRES: AsyncSQLConnector(),
    ConnectionType.MYSQL: AsyncSQLConnector(),
    ConnectionType.MSSQL: AsyncSQLConnector(),
    ConnectionType.KAFKA: AsyncKafkaConnector(),
    # ConnectionType.S3: Async connector will be added once aioboto3 support is introduced.
}
