from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from sqlmodel import Session

from db_connection.compat import extension_config as ext_config
from db_connection.compat.manager import ConnectionManager
from db_connection.compat.models import DBConnection
from db_connection.compat.schemas import ConnectionCreate, ConnectionRead, ConnectionUpdate


async def get_session() -> AsyncGenerator[Session, Any]:
    if ext_config.engine is None:
        raise RuntimeError("Database engine is not initialized")

    with Session(ext_config.engine) as session:
        yield session


@lru_cache(maxsize=1)
def get_connection_manager() -> ConnectionManager:
    return ConnectionManager(dbconnection_model=ext_config.DBConnectionModel,
                             max_connections=ext_config.max_connections)


@lru_cache
def get_db_connection_model() -> type[DBConnection]:
    return ext_config.DBConnectionModel


@lru_cache
def get_db_connection_create_schema() -> type[ConnectionCreate]:
    return ext_config.DBConnectionCreateSchema


@lru_cache
def get_db_connection_read_schema() -> type[ConnectionRead]:
    return ext_config.DBConnectionReadSchema


@lru_cache
def get_db_connection_update_schema() -> type[ConnectionUpdate]:
    return ext_config.DBConnectionUpdateSchema
