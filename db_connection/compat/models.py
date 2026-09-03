from datetime import datetime
from typing import Generic, TypeVar, Union

from pydantic import BaseModel, model_validator
from pydantic_core import PydanticUndefined
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

from db_connection.compat.connection_properties import (
    ConnectionPropertiesBase,
    CustomConnectionProperties,
    FTPConnectionProperties,
    KafkaConnectionProperties,
    S3ConnectionProperties,
    SFTPConnectionProperties,
    SqlConnectionProperties,
)
from db_connection.compat.meta import DBConnectionMetaclass
from db_connection.compat.sa_types import PydanticType
from db_connection.compat.types import ConnectionType, SQLConnectionTypes

ConnectionPropertiesType = Union[
    SqlConnectionProperties,
    KafkaConnectionProperties,
    S3ConnectionProperties,
    FTPConnectionProperties,
    SFTPConnectionProperties,
    # CustomConnectionProperties
]


TConnectionProperties = TypeVar("TConnectionProperties", bound=ConnectionPropertiesBase)
TModel = TypeVar("TModel", bound=SQLModel)

class DBConnection(SQLModel, Generic[TConnectionProperties], metaclass=DBConnectionMetaclass, table=False):
    """Базовая модель соединения с БД."""

    name: str = Field(..., max_length=100, description="Connection name")
    type: ConnectionType = Field(..., description="Connection type, e.g. 'postgres', 'mysql', 'kafka...")

    connection_properties: TConnectionProperties = Field(
        sa_type=PydanticType(ConnectionPropertiesType),  # type: ignore[arg-type]
        description="Connection properties",
    )

    is_deleted: bool = Field(default=False, nullable=False, description="Is connection active")

    created_at: datetime = Field(default_factory=datetime.now, description="Created time")
    updated_at: datetime = Field(default_factory=datetime.now, description="Updated time")

    model_config = SQLModelConfig(
        from_attributes=True,
        validate_assignment=True,
    )

    @model_validator(mode="before")
    def _force_is_deleted_default(cls, values):
        if isinstance(values, dict):
            v = values.get("is_deleted", PydanticUndefined)
            if v is PydanticUndefined or v is None:
                values["is_deleted"] = False
        return values

    @model_validator(mode="before")
    def _dispatch_properties(cls, values):  # type: ignore
        if not isinstance(values, dict):
            return values

        kind = values.get("type")
        props = values.get("connection_properties")

        if props is None:
            return values

        if isinstance(kind, str):
            kind = ConnectionType(kind)

        if kind in SQLConnectionTypes:
            values["connection_properties"] = SqlConnectionProperties.model_validate(props)
        elif kind is ConnectionType.KAFKA:
            values["connection_properties"] = KafkaConnectionProperties.model_validate(props)
        elif kind is ConnectionType.S3:
            values["connection_properties"] = S3ConnectionProperties.model_validate(props)
        elif kind is ConnectionType.FTP:
            values['connection_properties'] = FTPConnectionProperties.model_validate(props)
        elif kind is ConnectionType.SFTP:
            values['connection_properties'] = SFTPConnectionProperties.model_validate(props)
        elif kind is ConnectionType.CUSTOM:
            values["connection_properties"] = CustomConnectionProperties.model_validate(props)
        else:
            raise ValueError(f"Unsupported connection type: {kind!r}")

        return values



class DBConnectionBaseFilters(BaseModel, Generic[TModel]):
    """
    Пустой базовый класс фильтров.
    """
