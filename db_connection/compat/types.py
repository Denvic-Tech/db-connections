from enum import Enum
from typing import Final


class UndefinedType:
    def __repr__(self):
        return "Undefined"

    def __bool__(self):
        return False


Undefined: Final[UndefinedType] = UndefinedType()


class ConnectionType(str, Enum):
    MYSQL = "mysql"
    POSTGRES = "postgres"
    CLICKHOUSE = "clickhouse"
    MONGODB = "mongodb"
    MSSQL = "mssql"
    KAFKA = "kafka"
    S3 = "s3"
    ORACLE = "oracle"
    FTP = "ftp"
    SFTP = "sftp"
    CUSTOM = "custom"

    def __str__(self) -> str:
        return self.value


SQLConnectionTypes = [
    ConnectionType.MYSQL,
    ConnectionType.POSTGRES,
    ConnectionType.CLICKHOUSE,
    ConnectionType.MONGODB,
    ConnectionType.MSSQL,
    ConnectionType.ORACLE,
]

ASYNC_SUPPORTED_CONNECTION_TYPES: list[ConnectionType] = [
    ConnectionType.POSTGRES,
    ConnectionType.MSSQL,
    ConnectionType.MYSQL,
    ConnectionType.KAFKA,
    ConnectionType.S3,  # TODO: implement async connector
    ConnectionType.ORACLE,  # TODO: implement async connector
]


class ClickHouseDriverType(Enum):
    HTTP = "http"
    NATIVE = "native"


class MySQLDriverType(Enum):
    PYMYSQL = "pymysql"
    AIOMYSQL = "aiomysql"


class MSSQLDriverType(Enum):
    PYODBC = "pyodbc"
    AIOODBC = "aioodbc"


class PostgresDriverType(Enum):
    PSYCOPG2 = "psycopg2"
    PSYCOPG = "psycopg"
    ASYNCPG = "asyncpg"


class OracleDriverType(Enum):  # Добавлен новый класс
    ORACLEDB = "oracledb"
