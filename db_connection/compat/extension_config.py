from collections.abc import Callable
from typing import Annotated, Any

from cryptography.fernet import Fernet
from fastapi import Depends
from sqlalchemy import Engine
from sqlmodel import SQLModel

from db_connection.compat.models import DBConnection, DBConnectionBaseFilters
from db_connection.compat.schemas import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionUpdate,
    ConnectionUpsert,
)
from db_connection.compat.types import Undefined, UndefinedType

USE_AUTH = False

engine: Engine = None  # type: ignore

DBConnectionModel: type[DBConnection] = None  # type: ignore
DBConnectionCreateSchema: type[ConnectionCreate] = None  # type: ignore
DBConnectionReadSchema: type[ConnectionRead] = None  # type: ignore
DBConnectionUpdateSchema: type[ConnectionUpdate] = None  # type: ignore
DBConnectionUpsertSchema: type[ConnectionUpsert] = None  # type: ignore

fernet: Fernet | None = None

db_connection_pks: list[str] | None = None

UserModel: type[SQLModel] | UndefinedType = Undefined
GetUserDep = Annotated[UndefinedType, Depends(lambda: Undefined)]

disable_pk_filtration: Callable[[UserModel], bool] | None = lambda user: False
db_connection_to_user_fks_mapping: dict[str, str] | None = None
max_connections: int | None = None
filters: list[Any] | None = None
filters_model: DBConnectionBaseFilters | None = None
