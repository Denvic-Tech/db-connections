from __future__ import annotations

# pylint: disable=invalid-name
import asyncio
from dataclasses import dataclass
from functools import lru_cache
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, RootModel

from ..connectors.base import Connector
from ..domain.drivers import ODBCDriverOptions
from ..domain.entities import ConnectionCheckResult, ValidatedConnection
from ..errors import ConnectionTypeNotSupportedError

if TYPE_CHECKING:
    import sqlalchemy as sa
    import sqlalchemy.ext.asyncio as asa
else:
    sa = Any
    asa = Any

try:
    import sqlalchemy as sa
    import sqlalchemy.ext.asyncio as asa
except ImportError:
    sa = None
    asa = None

create_engine = None if sa is None else sa.create_engine
create_async_engine = None if asa is None else asa.create_async_engine

SQL_TYPES = {"postgres", "mysql", "clickhouse", "mssql", "oracle", "mongodb"}


@dataclass(frozen=True, slots=True)
class SQLDriverSpec:
    sync_dialect: str | None
    async_dialect: str | None


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeDriver:
    driver: str
    sqlalchemy_dialect: str
    use_async: bool


class SQLProperties(BaseModel):
    host: str
    port: int
    username: str
    database: str
    secure: bool = False
    connect_timeout: int | None = 30
    send_receive_timeout: int | None = 60
    sync_request_timeout: int | None = 60
    ca_cert_string: str | None = None
    verify: bool = False


class MSSQLTCPProperties(SQLProperties):
    model_config = ConfigDict(extra="forbid")


class MSSQLNamedInstanceProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    instance_name: str
    username: str
    database: str
    secure: bool = False
    connect_timeout: int | None = 30
    send_receive_timeout: int | None = 60
    sync_request_timeout: int | None = 60
    ca_cert_string: str | None = None
    verify: bool = False


class MSSQLProperties(RootModel[MSSQLTCPProperties | MSSQLNamedInstanceProperties]):
    pass


class SQLSecrets(BaseModel):
    password: str | None = None


@lru_cache(maxsize=1)
def get_default_postgres_driver() -> str:
    return "psycopg" if find_spec("psycopg") is not None else "psycopg2"


class SQLConnector(Connector):
    def __init__(self, *, preferred_mode: Literal["async", "sync"] = "async") -> None:
        self._preferred_mode = preferred_mode

    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        runtime = self._resolve_runtime_driver(connection)
        if runtime.use_async:
            return await self._check_async(connection)
        return await asyncio.to_thread(self._check_blocking, connection)

    async def get_client(self, connection: ValidatedConnection) -> asa.AsyncEngine | sa.Engine:
        runtime = self._resolve_runtime_driver(connection)
        if runtime.use_async:
            if create_async_engine is None:
                raise RuntimeError("SQL connections support requires Python's sqlalchemy module")
            return create_async_engine(self.build_connection_url(connection))
        return await asyncio.to_thread(self._get_client_blocking, connection)

    def build_connection_url(self, connection: ValidatedConnection) -> sa.URL | str:
        if sa is None:
            raise RuntimeError("SQL connections support requires Python's sqlalchemy module")

        if connection.type not in SQL_TYPES:
            raise ConnectionTypeNotSupportedError(connection.type)

        runtime = self._resolve_runtime_driver(connection)
        props = connection.properties.model_dump()
        secrets = {} if connection.secrets is None else connection.secrets.model_dump()
        query = self._build_query(
            connection.type,
            runtime.driver,
            props,
            connection.driver_options,
            use_async=runtime.use_async,
        )

        if connection.type == "mongodb":
            return sa.URL.create(
                drivername=runtime.sqlalchemy_dialect,
                username=props["username"],
                password=secrets.get("password"),
                host=props["host"],
                port=props["port"],
                database=props["database"],
                query=query,
            ).render_as_string(hide_password=False)

        if connection.type == "oracle":
            return sa.URL.create(
                drivername=runtime.sqlalchemy_dialect,
                host=props["host"],
                port=props["port"],
                username=props["username"],
                password=secrets.get("password"),
                query=query,
            )

        if connection.type == "mssql":
            return _build_mssql_url(
                drivername=runtime.sqlalchemy_dialect,
                props=props,
                password=secrets.get("password"),
                query=query,
            )

        return sa.URL.create(
            drivername=runtime.sqlalchemy_dialect,
            host=props["host"],
            port=props["port"],
            username=props["username"],
            password=secrets.get("password"),
            database=props["database"],
            query=query,
        )

    async def _check_async(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        if sa is None:
            raise RuntimeError("SQL connections support requires Python's sqlalchemy module")

        try:
            if create_async_engine is None:
                raise RuntimeError("SQL connections support requires Python's sqlalchemy module")
            engine = create_async_engine(self.build_connection_url(connection))
            async with engine.connect() as raw_connection:
                await raw_connection.execute(sa.text("SELECT 1"))
            await engine.dispose()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message="Connection successful.",
            )
        except Exception as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=str(exc),
                exception=str(exc),
            )

    def _check_blocking(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        try:
            engine = sa.create_engine(self.build_connection_url(connection))
            with engine.connect() as raw_connection:
                if connection.type == "oracle":
                    raw_connection.execute(sa.text("SELECT 1 FROM DUAL"))
                else:
                    raw_connection.execute(sa.text("SELECT 1"))
            engine.dispose()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message="Connection successful.",
            )
        except Exception as exc:
            return self._check_failure_result(
                connection,
                exc,
                message=str(exc),
                exception=str(exc),
            )

    def _get_client_blocking(self, connection: ValidatedConnection) -> sa.Engine:
        if create_engine is None:
            raise RuntimeError("SQL connections support requires Python's sqlalchemy module")
        return create_engine(self.build_connection_url(connection))

    def _resolve_runtime_driver(self, connection: ValidatedConnection) -> ResolvedRuntimeDriver:
        driver = self._resolve_driver(connection.type, connection.driver)
        driver_spec = self._resolve_driver_spec(connection.type, driver)

        if self._preferred_mode == "async":
            if driver_spec.async_dialect is not None:
                return ResolvedRuntimeDriver(
                    driver=driver,
                    sqlalchemy_dialect=driver_spec.async_dialect,
                    use_async=True,
                )
            if driver_spec.sync_dialect is not None:
                return ResolvedRuntimeDriver(
                    driver=driver,
                    sqlalchemy_dialect=driver_spec.sync_dialect,
                    use_async=False,
                )
            raise ConnectionTypeNotSupportedError(connection.type)

        if driver_spec.sync_dialect is not None:
            return ResolvedRuntimeDriver(
                driver=driver,
                sqlalchemy_dialect=driver_spec.sync_dialect,
                use_async=False,
            )
        raise ConnectionTypeNotSupportedError(connection.type)

    def _resolve_driver(self, connection_type: str, driver: str | None) -> str:
        if driver:
            return driver

        defaults = {
            "clickhouse": "native",
            "mysql": "pymysql",
            "mssql": "pyodbc",
            "oracle": "oracledb",
        }
        if connection_type == "postgres":
            return get_default_postgres_driver()
        return defaults.get(connection_type, "")

    def _resolve_driver_spec(self, connection_type: str, driver: str) -> SQLDriverSpec:
        mapping = {
            ("postgres", "psycopg"): SQLDriverSpec(
                sync_dialect="postgresql+psycopg",
                async_dialect="postgresql+psycopg",
            ),
            ("postgres", "psycopg2"): SQLDriverSpec(
                sync_dialect="postgresql+psycopg2",
                async_dialect=None,
            ),
            ("postgres", "asyncpg"): SQLDriverSpec(
                sync_dialect=None,
                async_dialect="postgresql+asyncpg",
            ),
            ("clickhouse", "native"): SQLDriverSpec(
                sync_dialect="clickhouse+native",
                async_dialect=None,
            ),
            ("clickhouse", "http"): SQLDriverSpec(
                sync_dialect="clickhouse+http",
                async_dialect=None,
            ),
            ("mysql", "pymysql"): SQLDriverSpec(
                sync_dialect="mysql+pymysql",
                async_dialect=None,
            ),
            ("mysql", "aiomysql"): SQLDriverSpec(
                sync_dialect=None,
                async_dialect="mysql+aiomysql",
            ),
            ("mssql", "pyodbc"): SQLDriverSpec(
                sync_dialect="mssql+pyodbc",
                async_dialect=None,
            ),
            ("mssql", "aioodbc"): SQLDriverSpec(
                sync_dialect=None,
                async_dialect="mssql+aioodbc",
            ),
            ("oracle", "oracledb"): SQLDriverSpec(
                sync_dialect="oracle+oracledb",
                async_dialect=None,
            ),
            ("mongodb", ""): SQLDriverSpec(
                sync_dialect="mongodb",
                async_dialect=None,
            ),
        }
        try:
            return mapping[(connection_type, driver)]
        except KeyError as exc:
            raise ConnectionTypeNotSupportedError(connection_type) from exc

    def _build_query(
        self,
        connection_type: str,
        driver: str,
        props: dict[str, Any],
        driver_options: object,
        *,
        use_async: bool,
    ) -> dict[str, str]:
        query: dict[str, Any] = {}
        secure = bool(props.get("secure"))
        verify = bool(props.get("verify"))
        ca_cert_string = props.get("ca_cert_string")
        connect_timeout = props.get("connect_timeout")
        send_receive_timeout = props.get("send_receive_timeout")
        sync_request_timeout = props.get("sync_request_timeout")

        if connection_type == "postgres":
            if connect_timeout is not None:
                query["connect_timeout"] = connect_timeout
            if secure:
                query["sslmode"] = "verify-full" if verify else "require"
                if use_async and driver == "asyncpg":
                    query["ssl"] = True
                if ca_cert_string:
                    query["sslrootcert"] = ca_cert_string
        elif connection_type == "mysql":
            if connect_timeout is not None:
                query["connect_timeout"] = connect_timeout
            if not use_async and send_receive_timeout is not None:
                query["read_timeout"] = send_receive_timeout
                query["write_timeout"] = send_receive_timeout
            if secure and ca_cert_string:
                query["ssl_ca"] = ca_cert_string
        elif connection_type == "mongodb":
            if connect_timeout is not None:
                query["connectTimeoutMS"] = connect_timeout * 1000
            if send_receive_timeout is not None:
                query["socketTimeoutMS"] = send_receive_timeout * 1000
            if secure:
                query["tls"] = True
                query["tlsAllowInvalidCertificates"] = not verify
                if ca_cert_string:
                    query["tlsCAFile"] = ca_cert_string
        elif connection_type == "clickhouse":
            if driver == "native":
                if secure:
                    query["secure"] = True
                    query["verify"] = verify
                    if ca_cert_string:
                        query["ca_certs"] = ca_cert_string
                if connect_timeout is not None:
                    query["connect_timeout"] = connect_timeout
                if sync_request_timeout is not None:
                    query["sync_request_timeout"] = sync_request_timeout
            else:
                query["protocol"] = "https" if secure else "http"
                query["verify"] = verify
                if ca_cert_string:
                    query["ca_certs"] = ca_cert_string
                if connect_timeout is not None:
                    query["timeout"] = connect_timeout
        elif connection_type == "mssql":
            query.update(
                _build_mssql_query(
                    driver_options=driver_options,
                    secure=secure,
                    verify=verify,
                    connect_timeout=connect_timeout,
                )
            )
        elif connection_type == "oracle":
            if connect_timeout is not None:
                query["tcp_connect_timeout"] = connect_timeout
            if secure:
                query["ssl_server_dn_match"] = verify
                if verify and ca_cert_string:
                    query["ssl_cert"] = ca_cert_string
            query["service_name"] = props["database"]

        return {key: str(value) for key, value in query.items()}


def _build_mssql_url(
    *,
    drivername: str,
    props: dict[str, Any],
    password: str | None,
    query: dict[str, str],
) -> sa.URL:
    host = props["host"]
    port = props.get("port")
    instance_name = props.get("instance_name")
    if instance_name:
        host = f"{host}\\{instance_name}"
        port = None

    return sa.URL.create(
        drivername=drivername,
        host=host,
        port=port,
        username=props["username"],
        password=password,
        database=props["database"],
        query=query,
    )


def _build_mssql_query(
    *,
    driver_options: object,
    secure: bool,
    verify: bool,
    connect_timeout: int | None,
) -> dict[str, Any]:
    options = _require_mssql_driver_options(driver_options)
    query: dict[str, Any] = {"driver": options.odbc_driver_name}
    if connect_timeout is not None:
        query["Connect Timeout"] = str(connect_timeout)
    query["Encrypt"] = "yes" if secure else "no"
    if secure:
        query["TrustServerCertificate"] = "no" if verify else "yes"
    return query


def _require_mssql_driver_options(driver_options: object) -> ODBCDriverOptions:
    if isinstance(driver_options, ODBCDriverOptions):
        return driver_options
    raise ValueError("MSSQL ODBC driver options are required.")
