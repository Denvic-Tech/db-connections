from __future__ import annotations

from cryptography.fernet import Fernet

from db_connection import ConnectionCheckResult
from db_connection.compat import extension_config as compat_ext_config
from db_connection.compat.connectors.ftp_sync import FTPConnector as CompatFTPConnector
from db_connection.compat.connectors.kafka_async import (
    AsyncKafkaConnector as CompatAsyncKafkaConnector,
)
from db_connection.compat.connectors.kafka_sync import KafkaConnector as CompatKafkaConnector
from db_connection.compat.connectors.s3_sync import S3Connector as CompatS3Connector
from db_connection.compat.connectors.sftp_sync import SFTPConnector as CompatSFTPConnector
from db_connection.compat.connectors.sql_async import AsyncSQLConnector as CompatAsyncSQLConnector
from db_connection.compat.connectors.sql_sync import SQLConnector as CompatSQLConnector
from db_connection.compat.encryption import decrypt_sensitive_fields, encrypt_sensitive_fields
from db_connection.compat.manager import ConnectionManager
from db_connection.compat.models import DBConnection
from db_connection.compat.types import ConnectionType
from db_connection.connectors.ftp import (
    FTPConnector as RuntimeFTPConnector,
    FTPMode as RuntimeFTPMode,
    SFTPConnector as RuntimeSFTPConnector,
)
from db_connection.connectors.kafka import (
    AsyncKafkaConnector as RuntimeAsyncKafkaConnector,
    KafkaConnector as RuntimeKafkaConnector,
)
from db_connection.connectors.s3 import S3Connector as RuntimeS3Connector
from db_connection.connectors.sql import SQLConnector as RuntimeSQLConnector
from db_connection.domain.drivers import ODBCDriverOptions


def test_compat_sql_connector_keeps_legacy_clickhouse_default_driver() -> None:
    connection = DBConnection(
        name="analytics",
        type=ConnectionType.CLICKHOUSE,
        connection_properties={
            "host": "localhost",
            "port": 8123,
            "username": "default",
            "password": "secret",
            "database": "default",
            "secure": False,
        },
    )

    url = CompatSQLConnector().build_connection_url(connection)

    assert str(url).startswith("clickhouse+http://")


def test_compat_connection_manager_maps_runtime_check_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_check(self: RuntimeSQLConnector, connection) -> ConnectionCheckResult:
        captured["driver"] = connection.driver
        captured["properties"] = connection.properties.model_dump()
        captured["secrets"] = {} if connection.secrets is None else connection.secrets.model_dump()
        return ConnectionCheckResult(name=connection.name, connected=True, message="ok")

    monkeypatch.setattr(RuntimeSQLConnector, "check", fake_check)

    connection = DBConnection(
        name="warehouse",
        type=ConnectionType.POSTGRES,
        connection_properties={
            "host": "localhost",
            "port": 5432,
            "username": "service",
            "password": "secret",
            "database": "analytics",
        },
    )

    status = ConnectionManager.check_connection(connection)

    assert status.connected is True
    assert status.message == "ok"
    assert captured["driver"] in {"psycopg", "psycopg2"}
    assert captured["properties"] == {
        "host": "localhost",
        "port": 5432,
        "username": "service",
        "database": "analytics",
        "secure": False,
        "connect_timeout": 30,
        "send_receive_timeout": 60,
        "sync_request_timeout": 60,
        "ca_cert_string": None,
        "verify": False,
    }
    assert captured["secrets"] == {"password": "secret"}


def test_compat_kafka_connector_splits_runtime_secrets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_client(self: RuntimeKafkaConnector, connection):
        captured["properties"] = connection.properties.model_dump()
        captured["secrets"] = {} if connection.secrets is None else connection.secrets.model_dump()
        return {"client": "kafka"}

    monkeypatch.setattr(RuntimeKafkaConnector, "get_client", fake_get_client)

    connection = DBConnection(
        name="events",
        type=ConnectionType.KAFKA,
        connection_properties={
            "bootstrap_servers": "kafka1:9092,kafka2:9092",
            "security_protocol": "SASL_PLAINTEXT",
            "sasl_mechanism": "PLAIN",
            "sasl_plain_username": "svc",
            "sasl_plain_password": "top-secret",
        },
    )

    client = CompatKafkaConnector().get_client(connection)

    assert client == {"client": "kafka"}
    assert captured["properties"] == {
        "bootstrap_servers": ["kafka1:9092", "kafka2:9092"],
        "security_protocol": "SASL_PLAINTEXT",
        "sasl_mechanism": "PLAIN",
        "sasl_plain_username": "svc",
        "client_id": "kafka_client",
        "request_timeout_ms": 30000,
    }
    assert captured["secrets"] == {"sasl_plain_password": "top-secret"}


def test_compat_async_kafka_connector_splits_runtime_secrets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_get_client(self: RuntimeAsyncKafkaConnector, connection):
        captured["properties"] = connection.properties.model_dump()
        captured["secrets"] = {} if connection.secrets is None else connection.secrets.model_dump()
        return {"client": "kafka-async"}

    monkeypatch.setattr(RuntimeAsyncKafkaConnector, "get_client", fake_get_client)

    connection = DBConnection(
        name="events",
        type=ConnectionType.KAFKA,
        connection_properties={
            "bootstrap_servers": ["kafka1:9092"],
            "sasl_plain_password": "top-secret",
        },
    )

    async def run() -> object:
        return await CompatAsyncKafkaConnector().get_client(connection)

    import asyncio

    client = asyncio.run(run())

    assert client == {"client": "kafka-async"}
    assert captured["properties"] == {
        "bootstrap_servers": ["kafka1:9092"],
        "security_protocol": "PLAINTEXT",
        "sasl_mechanism": None,
        "sasl_plain_username": None,
        "client_id": "kafka_client",
        "request_timeout_ms": 30000,
    }
    assert captured["secrets"] == {"sasl_plain_password": "top-secret"}


def test_compat_s3_connector_splits_runtime_secrets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_client(self: RuntimeS3Connector, connection):
        captured["properties"] = connection.properties.model_dump()
        captured["secrets"] = {} if connection.secrets is None else connection.secrets.model_dump()
        return {"client": "s3"}

    monkeypatch.setattr(RuntimeS3Connector, "get_client", fake_get_client)

    connection = DBConnection(
        name="objects",
        type=ConnectionType.S3,
        connection_properties={
            "bucket": "bucket",
            "region_name": "eu-central-1",
            "endpoint_url": "https://s3.example.test",
            "access_token_id": "key-id",
            "access_token_key": "key-secret",
            "session_token": "session-token",
            "prefix": "uploads",
        },
    )

    client = CompatS3Connector().get_client(connection)

    assert client == {"client": "s3"}
    assert captured["properties"] == {
        "bucket": "bucket",
        "region_name": "eu-central-1",
        "endpoint_url": "https://s3.example.test",
        "use_ssl": True,
        "verify": True,
        "path_style": False,
        "signature_version": None,
        "prefix": "uploads",
    }
    assert captured["secrets"] == {
        "access_token_id": "key-id",
        "access_token_key": "key-secret",
        "session_token": "session-token",
    }


def test_compat_ftp_connector_splits_runtime_secrets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_client(self: RuntimeFTPConnector, connection):
        captured["properties"] = connection.properties.model_dump()
        captured["secrets"] = {} if connection.secrets is None else connection.secrets.model_dump()
        return {"client": "ftp"}

    monkeypatch.setattr(RuntimeFTPConnector, "get_client", fake_get_client)

    connection = DBConnection(
        name="ftp-files",
        type=ConnectionType.FTP,
        connection_properties={
            "host": "ftp.example.test",
            "port": 21,
            "mode": "ftp",
            "username": "svc",
            "password": "top-secret",
            "initial_directory": "/uploads",
        },
    )

    client = CompatFTPConnector().get_client(connection)

    assert client == {"client": "ftp"}
    assert captured["properties"] == {
        "host": "ftp.example.test",
        "port": 21,
        "mode": RuntimeFTPMode.FTP,
        "username": "svc",
        "anonymous": False,
        "encoding": "utf-8",
        "initial_directory": "/uploads",
        "ssl_context": None,
        "verify_ssl": True,
        "certfile": None,
        "keyfile": None,
    }
    assert captured["secrets"] == {"password": "top-secret"}


def test_compat_sftp_connector_splits_runtime_secrets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_client(self: RuntimeSFTPConnector, connection):
        captured["properties"] = connection.properties.model_dump()
        captured["secrets"] = {} if connection.secrets is None else connection.secrets.model_dump()
        return {"client": "sftp"}

    monkeypatch.setattr(RuntimeSFTPConnector, "get_client", fake_get_client)

    connection = DBConnection(
        name="sftp-files",
        type=ConnectionType.SFTP,
        connection_properties={
            "host": "sftp.example.test",
            "port": 22,
            "username": "svc",
            "password": "top-secret",
            "private_key_string": "KEY",
            "private_key_passphrase": "phrase",
            "initial_directory": "/exports",
            "allow_agent": True,
        },
    )

    client = CompatSFTPConnector().get_client(connection)

    assert client == {"client": "sftp"}
    assert captured["properties"] == {
        "host": "sftp.example.test",
        "port": 22,
        "username": "svc",
        "private_key_path": None,
        "initial_directory": "/exports",
        "allow_agent": True,
    }
    assert captured["secrets"] == {
        "password": "top-secret",
        "private_key_passphrase": "phrase",
        "private_key_string": "KEY",
    }


def test_compat_async_sql_connector_delegates_to_runtime_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_get_client(self: RuntimeSQLConnector, connection):
        captured["driver"] = connection.driver
        return {"client": "sql-async"}

    monkeypatch.setattr(RuntimeSQLConnector, "get_client", fake_get_client)

    connection = DBConnection(
        name="warehouse",
        type=ConnectionType.MYSQL,
        connection_properties={
            "host": "localhost",
            "port": 3306,
            "username": "service",
            "password": "secret",
            "database": "analytics",
        },
    )

    async def run() -> object:
        return await CompatAsyncSQLConnector().get_client(connection)

    import asyncio

    client = asyncio.run(run())

    assert client == {"client": "sql-async"}
    assert captured["driver"] == "aiomysql"


def test_compat_async_sql_connector_keeps_explicit_sync_driver_for_runtime_fallback(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_get_client(self: RuntimeSQLConnector, connection):
        captured["driver"] = connection.driver
        return {"client": "sql-sync-fallback"}

    monkeypatch.setattr(RuntimeSQLConnector, "get_client", fake_get_client)

    connection = DBConnection(
        name="warehouse",
        type=ConnectionType.MYSQL,
        connection_properties={
            "host": "localhost",
            "port": 3306,
            "username": "service",
            "password": "secret",
            "database": "analytics",
            "driver_name": "pymysql",
        },
    )

    async def run() -> object:
        return await CompatAsyncSQLConnector().get_client(connection)

    import asyncio

    client = asyncio.run(run())

    assert client == {"client": "sql-sync-fallback"}
    assert captured["driver"] == "pymysql"


def test_compat_mssql_bridge_maps_legacy_driver_name_to_runtime_driver_options() -> None:
    from db_connection.compat.runtime_bridge import to_runtime_draft

    connection = DBConnection(
        name="warehouse",
        type=ConnectionType.MSSQL,
        connection_properties={
            "host": "localhost",
            "port": 1433,
            "username": "service",
            "password": "secret",
            "database": "analytics",
            "driver_name": "ODBC Driver 18 for SQL Server",
        },
    )

    sync_draft = to_runtime_draft(connection, mode="sync")
    async_draft = to_runtime_draft(connection, mode="async")

    assert sync_draft.driver == "pyodbc"
    assert async_draft.driver == "aioodbc"
    assert isinstance(sync_draft.driver_options, ODBCDriverOptions)
    assert isinstance(async_draft.driver_options, ODBCDriverOptions)
    assert sync_draft.driver_options.odbc_driver_name == "ODBC Driver 18 for SQL Server"
    assert async_draft.driver_options.odbc_driver_name == "ODBC Driver 18 for SQL Server"


def test_compat_encryption_roundtrip() -> None:
    original_fernet = compat_ext_config.fernet
    compat_ext_config.fernet = Fernet(Fernet.generate_key())
    try:
        payload = {
            "password": "secret",
            "sasl_plain_password": "kafka-secret",
            "access_token_id": "key-id",
            "plain": "value",
        }

        encrypted = encrypt_sensitive_fields(payload)
        decrypted = decrypt_sensitive_fields(encrypted)

        assert encrypted["plain"] == "value"
        assert encrypted["password"].startswith("fernet$")
        assert encrypted["sasl_plain_password"].startswith("fernet$")
        assert decrypted == payload
    finally:
        compat_ext_config.fernet = original_fernet
