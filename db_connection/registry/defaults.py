from __future__ import annotations

from ..connectors import (
    AsyncKafkaConnector,
    FTPConnector,
    S3Connector,
    SFTPConnector,
    SQLConnector,
)
from ..connectors.ftp import FTPProperties, FTPSecrets, SFTPProperties, SFTPSecrets
from ..connectors.kafka import KafkaProperties, KafkaSecrets
from ..connectors.s3 import S3Properties, S3Secrets
from ..connectors.sql import MSSQLProperties, SQLProperties, SQLSecrets
from ..domain.drivers import DriverSpec, NoDriverOptions, ODBCDriverOptions
from ..domain.specs import KindSpec, TypeSpec
from .base import ConnectionRegistry


def build_default_registry() -> ConnectionRegistry:
    registry = ConnectionRegistry()
    sql_capabilities = {"check", "client", "query"}
    queue_capabilities = {"check", "client", "publish"}
    file_capabilities = {"check", "client", "list_objects"}
    registry.register_kind(KindSpec(name="sql", capabilities=sql_capabilities))
    registry.register_kind(KindSpec(name="queue", capabilities=queue_capabilities))
    registry.register_kind(KindSpec(name="file", capabilities=file_capabilities))

    sql_common = {
        "properties_model": SQLProperties,
        "secrets_model": SQLSecrets,
        "public_model": SQLProperties,
        "capabilities": {"check", "client"},
    }
    postgres_driver_specs = [
        DriverSpec(name="psycopg", options_model=NoDriverOptions),
        DriverSpec(name="psycopg2", options_model=NoDriverOptions),
        DriverSpec(name="asyncpg", options_model=NoDriverOptions),
    ]
    mysql_driver_specs = [
        DriverSpec(name="pymysql", options_model=NoDriverOptions),
        DriverSpec(name="aiomysql", options_model=NoDriverOptions),
    ]
    clickhouse_driver_specs = [
        DriverSpec(name="native", options_model=NoDriverOptions),
        DriverSpec(name="http", options_model=NoDriverOptions),
    ]
    mssql_driver_specs = [
        DriverSpec(name="pyodbc", options_model=ODBCDriverOptions),
        DriverSpec(name="aioodbc", options_model=ODBCDriverOptions),
    ]
    oracle_driver_specs = [DriverSpec(name="oracledb", options_model=NoDriverOptions)]
    kafka_capabilities = {"check", "client"}
    kafka_capabilities.add("publish")
    s3_capabilities = {"check", "client"}
    s3_capabilities.add("list_objects")
    file_connector_capabilities = {"check", "client"}

    registry.register_type(
        TypeSpec(
            name="postgres",
            kind="sql",
            default_driver="psycopg",
            driver_specs=postgres_driver_specs,
            connector_factory=SQLConnector,
            **sql_common,
        )
    )
    registry.register_type(
        TypeSpec(
            name="mysql",
            kind="sql",
            default_driver="pymysql",
            driver_specs=mysql_driver_specs,
            connector_factory=SQLConnector,
            **sql_common,
        )
    )
    registry.register_type(
        TypeSpec(
            name="clickhouse",
            kind="sql",
            default_driver="native",
            driver_specs=clickhouse_driver_specs,
            connector_factory=SQLConnector,
            **sql_common,
        )
    )
    registry.register_type(
        TypeSpec(
            name="mssql",
            kind="sql",
            default_driver="pyodbc",
            driver_specs=mssql_driver_specs,
            connector_factory=SQLConnector,
            properties_model=MSSQLProperties,
            secrets_model=SQLSecrets,
            public_model=MSSQLProperties,
            capabilities={"check", "client"},
        )
    )
    registry.register_type(
        TypeSpec(
            name="oracle",
            kind="sql",
            default_driver="oracledb",
            driver_specs=oracle_driver_specs,
            connector_factory=SQLConnector,
            **sql_common,
        )
    )
    registry.register_type(
        TypeSpec(
            name="mongodb",
            kind="sql",
            supported_drivers=set(),
            connector_factory=SQLConnector,
            properties_model=SQLProperties,
            secrets_model=SQLSecrets,
            public_model=SQLProperties,
            capabilities={"check", "client"},
        )
    )
    registry.register_type(
        TypeSpec(
            name="kafka",
            kind="queue",
            properties_model=KafkaProperties,
            secrets_model=KafkaSecrets,
            public_model=KafkaProperties,
            connector_factory=AsyncKafkaConnector,
            capabilities=kafka_capabilities,
        )
    )
    registry.register_type(
        TypeSpec(
            name="s3",
            kind="file",
            properties_model=S3Properties,
            secrets_model=S3Secrets,
            public_model=S3Properties,
            connector_factory=S3Connector,
            default_driver=None,
            capabilities=s3_capabilities,
        )
    )
    registry.register_type(
        TypeSpec(
            name="ftp",
            kind="file",
            properties_model=FTPProperties,
            secrets_model=FTPSecrets,
            public_model=FTPProperties,
            connector_factory=FTPConnector,
            capabilities=file_connector_capabilities,
        )
    )
    registry.register_type(
        TypeSpec(
            name="sftp",
            kind="file",
            properties_model=SFTPProperties,
            secrets_model=SFTPSecrets,
            public_model=SFTPProperties,
            connector_factory=SFTPConnector,
            capabilities=file_connector_capabilities,
        )
    )
    return registry
