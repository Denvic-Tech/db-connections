from typing import Any, Optional, Union

from pydantic import BaseModel, Field, model_validator
from pystructor import omit, partial

from db_connection.compat.connection_properties import (
    CustomConnectionProperties,
    KafkaConnectionProperties,
    S3ConnectionProperties,
    SqlConnectionProperties,
)
from db_connection.compat.models import DBConnection as DBConnectionModel


@omit(SqlConnectionProperties, "password")
class SqlConnectionPropertiesRead(BaseModel):
    """Публичные свойства SQL-подключения без пароля."""

    class Config:
        from_attributes = True


@omit(KafkaConnectionProperties, "sasl_plain_password")
class KafkaConnectionPropertiesRead(BaseModel):
    """Публичные свойства Kafka-подключения без чувствительных данных."""

    class Config:
        from_attributes = True


class S3ConnectionPropertiesRead(BaseModel):
    """Публичные свойства S3-подключения без чувствительных данных."""

    bucket: str
    region_name: str | None = None
    endpoint_url: str | None = None
    use_ssl: bool = True
    path_style: bool = False
    signature_version: str | None = None
    prefix: str

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def from_internal_model(cls, value: Any) -> Any:
        if isinstance(value, S3ConnectionProperties):
            return value.model_dump(
                exclude={
                    "access_token_id",
                    "access_token_key",
                    "session_token",
                }
            )
        return value


ConnectionPropertiesRead = Union[
    SqlConnectionPropertiesRead,
    KafkaConnectionPropertiesRead,
    S3ConnectionPropertiesRead,
    CustomConnectionProperties,
]


@omit(DBConnectionModel, "id", "created_at", "updated_at")
class ConnectionCreate(BaseModel):
    """Схема для создания соединения с БД."""


class ConnectionRead(DBConnectionModel):
    """Схема для чтения соединения с БД."""

    connection_properties: ConnectionPropertiesRead  # type: ignore[assignment]

    class Config:
        from_attributes = True


@partial(DBConnectionModel)
class ConnectionUpdate(BaseModel):
    """Схема для обновления соединения с БД."""


@omit(DBConnectionModel, "created_at", "updated_at")
class ConnectionUpsert(BaseModel):
    """Схема для создания/обновления соединения с БД."""


class ConnectionStatus(BaseModel):
    """Схема для ответа о состоянии соединения с БД."""

    name: str = Field(..., max_length=100, description="Connection name")
    connected: bool = Field(..., description="Connection status")
    message: str | None = Field(default=None, description="Connection message")
    exception: str | None = Field(default=None, description="Connection exception")

    @model_validator(mode='before')
    @classmethod
    def validate_exception(cls, data: Any):
        if isinstance(data, dict) and 'exception' in data and data['exception'] is not None:
            data['exception'] = str(data['exception'])

        return data
