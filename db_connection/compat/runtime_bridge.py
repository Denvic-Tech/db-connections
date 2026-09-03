from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
from typing import Any, Literal

from db_connection.application.validation import ValidationService
from db_connection.compat import defaults, exceptions as compat_exc, types
from db_connection.compat.models import DBConnection
from db_connection.compat.schemas import ConnectionStatus
from db_connection.domain.drivers import ODBCDriverOptions
from db_connection.domain.entities import ConnectionCheckResult, ConnectionDraft, ValidatedConnection
from db_connection.registry.base import ConnectionRegistry
from db_connection.registry.defaults import build_default_registry

RUNTIME_BACKED_TYPES = frozenset(
    {
        types.ConnectionType.POSTGRES,
        types.ConnectionType.MYSQL,
        types.ConnectionType.CLICKHOUSE,
        types.ConnectionType.MONGODB,
        types.ConnectionType.MSSQL,
        types.ConnectionType.ORACLE,
        types.ConnectionType.KAFKA,
        types.ConnectionType.S3,
        types.ConnectionType.FTP,
        types.ConnectionType.SFTP,
    }
)
PASSWORD_SECRET_KEYS = ("password",)
KAFKA_SECRET_KEYS = ("sasl_plain_password",)
S3_SECRET_KEYS = ("access_token_id", "access_token_key", "session_token")
SFTP_SECRET_KEYS = ("password", "private_key_passphrase", "private_key_string")
ASYNC_SQL_DRIVER_DEFAULTS = {
    types.ConnectionType.POSTGRES: "asyncpg",
    types.ConnectionType.MYSQL: "aiomysql",
    types.ConnectionType.MSSQL: "aioodbc",
}


@lru_cache(maxsize=1)
def get_runtime_registry() -> ConnectionRegistry:
    return build_default_registry()


@lru_cache(maxsize=1)
def get_validation_service() -> ValidationService:
    return ValidationService(get_runtime_registry())


def uses_runtime_bridge(connection_type: types.ConnectionType) -> bool:
    return connection_type in RUNTIME_BACKED_TYPES


def to_runtime_validated(
    db_connection: DBConnection[Any],
    *,
    mode: Literal["sync", "async"] = "sync",
) -> ValidatedConnection:
    connection_type = db_connection.type
    if not uses_runtime_bridge(connection_type):
        raise compat_exc.WrongDBTypeError(type_received=connection_type)
    return get_validation_service().validate(to_runtime_draft(db_connection, mode=mode))


def to_runtime_draft(
    db_connection: DBConnection[Any],
    *,
    mode: Literal["sync", "async"] = "sync",
) -> ConnectionDraft:
    connection_type = db_connection.type
    if not uses_runtime_bridge(connection_type):
        raise compat_exc.WrongDBTypeError(type_received=connection_type)

    registry = get_runtime_registry()
    spec = registry.get_type(connection_type.value)
    properties, secrets, driver, driver_options = _split_connection_data(
        connection_type,
        db_connection.connection_properties,
        mode=mode,
    )

    return ConnectionDraft(
        name=db_connection.name,
        kind=spec.kind,
        type=connection_type.value,
        driver=driver,
        driver_options=driver_options,
        properties=properties,
        secrets=secrets,
    )


def to_legacy_status(result: ConnectionCheckResult) -> ConnectionStatus:
    return ConnectionStatus.model_validate(asdict(result))


def _split_connection_data(
    connection_type: types.ConnectionType,
    properties: Any,
    *,
    mode: Literal["sync", "async"] = "sync",
) -> tuple[dict[str, Any], dict[str, Any], str | None, ODBCDriverOptions | None]:
    raw = properties.model_dump(mode="python")
    driver_options = None

    if connection_type in types.SQLConnectionTypes:
        legacy_driver_name = raw.pop("driver_name", None)
        password = raw.pop("password", None)
        driver = None
        if connection_type == types.ConnectionType.MSSQL:
            if legacy_driver_name is None:
                raise compat_exc.DriverNotSpecifiedError(db_type=types.ConnectionType.MSSQL)
            driver_options = ODBCDriverOptions(odbc_driver_name=legacy_driver_name)
            driver = "aioodbc" if mode == "async" else "pyodbc"
        else:
            driver = legacy_driver_name
            if mode == "async" and driver is None:
                driver = _resolve_async_sql_driver(connection_type)
            if connection_type == types.ConnectionType.CLICKHOUSE and driver is None:
                driver = defaults.CH_DRIVER.value
        sql_secrets = _extract_secrets(raw={}, secret_keys=PASSWORD_SECRET_KEYS, values={"password": password})
        return _build_connection_data(raw, sql_secrets, driver, driver_options)

    if connection_type == types.ConnectionType.KAFKA:
        password = raw.pop("sasl_plain_password", None)
        kafka_secrets = _extract_secrets(
            raw={},
            secret_keys=KAFKA_SECRET_KEYS,
            values={"sasl_plain_password": password},
        )
        return _build_connection_data(raw, kafka_secrets, None, None)

    if connection_type == types.ConnectionType.S3:
        secrets = _extract_secrets(raw=raw, secret_keys=S3_SECRET_KEYS)
        return _build_connection_data(raw, secrets, None, None)

    if connection_type == types.ConnectionType.FTP:
        password = raw.pop("password", None)
        ftp_secrets = _extract_secrets(raw={}, secret_keys=PASSWORD_SECRET_KEYS, values={"password": password})
        return _build_connection_data(raw, ftp_secrets, None, None)

    if connection_type == types.ConnectionType.SFTP:
        secrets = _extract_secrets(raw=raw, secret_keys=SFTP_SECRET_KEYS)
        return _build_connection_data(raw, secrets, None, None)

    raise compat_exc.WrongDBTypeError(type_received=connection_type)


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _resolve_async_sql_driver(connection_type: types.ConnectionType) -> str | None:
    return ASYNC_SQL_DRIVER_DEFAULTS.get(connection_type)


def _build_connection_data(
    properties: dict[str, Any],
    secrets: dict[str, Any],
    driver: str | None,
    driver_options: ODBCDriverOptions | None,
) -> tuple[dict[str, Any], dict[str, Any], str | None, ODBCDriverOptions | None]:
    connection_data = [properties, secrets]
    connection_data.extend((driver, driver_options))
    return tuple(connection_data)  # type: ignore[return-value]


def _extract_secrets(
    *,
    raw: dict[str, Any],
    secret_keys: tuple[str, ...],
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    secret_values = {} if values is None else dict(values)
    for secret_key in secret_keys:
        if secret_key not in secret_values:
            secret_values[secret_key] = raw.pop(secret_key, None)
    return _drop_none(secret_values)
