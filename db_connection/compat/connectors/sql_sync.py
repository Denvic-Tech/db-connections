from functools import lru_cache
from importlib.util import find_spec

from sqlalchemy import URL, Engine

from db_connection._async_utils import run_maybe_async
from db_connection.compat import exceptions as exc, types
from db_connection.compat.connectors.base import BaseConnector
from db_connection.compat.models import DBConnection
from db_connection.compat.runtime_bridge import to_legacy_status, to_runtime_validated
from db_connection.compat.schemas import ConnectionStatus
from db_connection.connectors.sql import SQLConnector as RuntimeSQLConnector


@lru_cache(maxsize=1)
def get_pg_driver():
    if find_spec("psycopg") is not None:
        return types.PostgresDriverType.PSYCOPG
    if find_spec("psycopg2") is not None:
        return types.PostgresDriverType.PSYCOPG2
    raise ImportError("No PostgreSQL driver found, please, install psycopg with `pip install psycopg`")


class SQLConnector(BaseConnector[Engine]):
    """Connector for all SQLAlchemy-compatible databases."""

    def __init__(self) -> None:
        self._runtime_connector = RuntimeSQLConnector(preferred_mode="sync")

    def build_connection_url(self, db_conn: DBConnection[Engine]) -> URL | str:
        try:
            return self._runtime_connector.build_connection_url(to_runtime_validated(db_conn))
        except Exception as error:
            raise self._map_runtime_error(db_conn.type, error) from error

    def check(self, connection: DBConnection[Engine]) -> ConnectionStatus:
        try:
            return to_legacy_status(run_maybe_async(self._runtime_connector.check(to_runtime_validated(connection))))
        except exc.WrongDBTypeError:
            raise
        except Exception as error:
            return ConnectionStatus(
                name=connection.name,
                connected=False,
                message=str(error),
                exception=str(error),
            )

    def get_client(self, connection: DBConnection[Engine]) -> Engine | None:
        return run_maybe_async(self._runtime_connector.get_client(to_runtime_validated(connection)))

    def _map_runtime_error(self, connection_type: types.ConnectionType, error: Exception) -> Exception:
        if isinstance(error, exc.WrongDBTypeError | exc.DriverNotSpecifiedError):
            return error
        if isinstance(error, ValueError):
            if connection_type == types.ConnectionType.MSSQL and "driver" in str(error).lower():
                return exc.DriverNotSpecifiedError(db_type=connection_type)
            if connection_type not in types.SQLConnectionTypes:
                return exc.WrongDBTypeError(type_received=connection_type)
        return error
