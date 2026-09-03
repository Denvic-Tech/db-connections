from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from ..domain.drivers import DriverOptionsBase
from .sa_types import DriverOptionsType


class DefaultStoredConnection(
    SQLModel, table=False
):  # Overriding table=True only in the external project. For codex: don't change to True!
    __tablename__ = "db_connections"

    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    kind: str = Field(index=True)
    type: str = Field(index=True)
    driver: str | None = Field(default=None)
    driver_options_json: DriverOptionsBase | None = Field(
        default=None,
        sa_column=sa.Column(DriverOptionsType(), nullable=True),
    )
    properties_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    secrets_ciphertext: str = Field(default="{}")
    labels_json: dict[str, str] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    extra_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    deleted_at: datetime | None = Field(default=None, nullable=True)


def ensure_stored_connection_table_model(
    model_class: type[DefaultStoredConnection],
) -> type[DefaultStoredConnection]:
    if not hasattr(model_class, "__table__"):
        raise TypeError(
            "Default SQLModel storage requires a SQLModel class declared with table=True. "
            "Create a project table model that inherits DefaultStoredConnection and pass it as model_class."
        )
    return model_class
