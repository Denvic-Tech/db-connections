from db_connection.compat.connectors.base import BaseConnector
from db_connection.compat.connectors.ftp_sync import FTPConnector
from db_connection.compat.connectors.kafka_sync import KafkaConnector
from db_connection.compat.connectors.s3_sync import S3Connector
from db_connection.compat.connectors.sftp_sync import SFTPConnector
from db_connection.compat.connectors.sql_sync import SQLConnector
from db_connection.compat.types import ConnectionType

CONNECTOR_REGISTRY: dict[ConnectionType, BaseConnector] = {
    ConnectionType.POSTGRES: SQLConnector(),
    ConnectionType.MYSQL: SQLConnector(),
    ConnectionType.CLICKHOUSE: SQLConnector(),
    ConnectionType.MSSQL: SQLConnector(),
    ConnectionType.ORACLE: SQLConnector(),
    ConnectionType.MONGODB: SQLConnector(),
    ConnectionType.KAFKA: KafkaConnector(),
    ConnectionType.S3: S3Connector(),
    ConnectionType.FTP: FTPConnector(),
    ConnectionType.SFTP: SFTPConnector(),
}
