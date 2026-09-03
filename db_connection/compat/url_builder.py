from abc import ABC, abstractmethod
from typing import Any, Union

from db_connection.compat import exceptions as exc, types
from db_connection.compat.connection_properties import SqlConnectionProperties
from db_connection.compat.models import ConnectionPropertiesType


class QueryAdapter(ABC):
    @abstractmethod
    def to_query(self, props: ConnectionPropertiesType | None) -> dict[str, Any]:
        ...


class PostgresAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q
        # connection timeout
        if props.connect_timeout is not None:
            q["connect_timeout"] = props.connect_timeout
        # SSL settings
        if props.secure:
            q["sslmode"] = "verify-full" if props.verify else "require"
            if props.ca_cert_string:
                q["sslrootcert"] = props.ca_cert_string
        return q


class AsyncpgAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q

        # SSL settings
        if props.secure:
            q["sslmode"] = "verify-full" if props.verify else "require"
            if props.ca_cert_string:
                q["sslrootcert"] = props.ca_cert_string
            # asyncpg uses separate ssl parameter
            q["ssl"] = True
        return q


class PyMySQLAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q
        if props.connect_timeout is not None:
            q["connect_timeout"] = props.connect_timeout
        if props.secure and props.ca_cert_string:
            q["ssl_ca"] = props.ca_cert_string
        # MySQL read/write timeouts in seconds
        if props.send_receive_timeout is not None:
            q["read_timeout"] = props.send_receive_timeout
            q["write_timeout"] = props.send_receive_timeout
        return q


class AIOSQLAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q
        if props.connect_timeout is not None:
            q["connect_timeout"] = props.connect_timeout
        if props.secure and props.ca_cert_string:
            q["ssl_ca"] = props.ca_cert_string

        return q


class MongoAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q
        # timeouts in ms for Mongo
        if props.connect_timeout is not None:
            q["connectTimeoutMS"] = props.connect_timeout * 1000
        if props.send_receive_timeout is not None:
            q["socketTimeoutMS"] = props.send_receive_timeout * 1000
        if props.secure:
            q["tls"] = True
            q["tlsAllowInvalidCertificates"] = not props.verify
            if props.ca_cert_string:
                q["tlsCAFile"] = props.ca_cert_string
        return q


class ClickHouseNativeAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q
        if props.secure:
            q["secure"] = True
            if props.ca_cert_string:
                q["ca_certs"] = props.ca_cert_string
            q["verify"] = props.verify
        if props.connect_timeout is not None:
            q["connect_timeout"] = props.connect_timeout
        if props.sync_request_timeout is not None:
            q["sync_request_timeout"] = props.sync_request_timeout
        return q


class ClickHouseHttpAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q
        q["protocol"] = "https" if props.secure else "http"
        q["verify"] = props.verify
        if props.ca_cert_string:
            q["ca_certs"] = props.ca_cert_string
        if props.connect_timeout is not None:
            q["timeout"] = props.connect_timeout
        return q


class PYODBCMSSQLAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}

        if props is None:
            return q

        if not props.driver_name:
            raise exc.DriverNotSpecifiedError(db_type=types.ConnectionType.MSSQL)

        q["driver"] = props.driver_name

        if props.connect_timeout is not None:
            q["Connect Timeout"] = str(props.connect_timeout)

        if props.secure:
            q["Encrypt"] = "yes"
            q["TrustServerCertificate"] = "no" if props.verify else "yes"
        else:
            q["Encrypt"] = "no"

        return q


class AIODBCMSSQLAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}

        if props is None:
            return q

        if not props.driver_name:
            raise exc.DriverNotSpecifiedError(db_type=types.ConnectionType.MSSQL)

        q["driver"] = props.driver_name

        if props.connect_timeout is not None:
            q["Connect Timeout"] = str(props.connect_timeout)

        if props.secure:
            q["Encrypt"] = "yes"
            q["TrustServerCertificate"] = "no" if props.verify else "yes"
        else:
            q["Encrypt"] = "no"

        return q


class OracleAdapter(QueryAdapter):
    def to_query(self, props: SqlConnectionProperties | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        if props is None:
            return q
        if props.connect_timeout is not None:
            q["tcp_connect_timeout"] = props.connect_timeout

        # SSL (только если реально используется)
        if props.secure:
            q["ssl_server_dn_match"] = props.verify
            if props.verify and props.ca_cert_string:
                q["ssl_cert"] = props.ca_cert_string

        # Вместо DB -> service_name
        q['service_name'] = props.database
        return q


# Registry mapping
DIALECTS: dict[
    Union[
        types.ConnectionType,
        tuple[types.ConnectionType, Union[
            types.ClickHouseDriverType,
            types.PostgresDriverType,
            types.MySQLDriverType,
            types.MSSQLDriverType,
            types.OracleDriverType
        ]]
    ], tuple[str, QueryAdapter]
] = {
    # POSTGRES
    (types.ConnectionType.POSTGRES, types.PostgresDriverType.PSYCOPG): (
        "postgresql+psycopg", PostgresAdapter()
    ),
    (types.ConnectionType.POSTGRES, types.PostgresDriverType.PSYCOPG2): (
        "postgresql+psycopg2", PostgresAdapter()
    ),
    (types.ConnectionType.POSTGRES, types.PostgresDriverType.ASYNCPG): (
        "postgresql+asyncpg", AsyncpgAdapter()
    ),

    # CLICKHOUSE
    (types.ConnectionType.CLICKHOUSE, types.ClickHouseDriverType.NATIVE): (
        "clickhouse+native", ClickHouseNativeAdapter()
    ),
    (types.ConnectionType.CLICKHOUSE, types.ClickHouseDriverType.HTTP): (
        "clickhouse+http", ClickHouseHttpAdapter()
    ),

    # MYSQL
    (types.ConnectionType.MYSQL, types.MySQLDriverType.PYMYSQL): (
        "mysql+pymysql", PyMySQLAdapter()
    ),
    (types.ConnectionType.MYSQL, types.MySQLDriverType.AIOMYSQL): (
        "mysql+aiomysql", AIOSQLAdapter()
    ),

    # MSSQL
    (types.ConnectionType.MSSQL, types.MSSQLDriverType.PYODBC): (
        "mssql+pyodbc", PYODBCMSSQLAdapter()
    ),
    (types.ConnectionType.MSSQL, types.MSSQLDriverType.AIOODBC): (
        "mssql+aioodbc", AIODBCMSSQLAdapter()
    ),

    (types.ConnectionType.ORACLE, types.OracleDriverType.ORACLEDB): (
        "oracle+oracledb", OracleAdapter()
    ),

    types.ConnectionType.MONGODB: ("mongodb", MongoAdapter()),
}
