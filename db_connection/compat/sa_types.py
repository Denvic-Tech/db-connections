from typing import Any

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB

from db_connection.compat.encryption import decrypt_sensitive_fields, encrypt_sensitive_fields


class PydanticType(sa.types.TypeDecorator):
    """SQLAlchemy type decorator for arbitrary Pydantic v2 models, stored as JSON/JSONB."""
    impl = sa.types.JSON
    cache_ok = True

    def __init__(self, pydantic_type: type, *args, **kwargs):
        """
        :param pydantic_type: the Pydantic model class to (de)serialize
        """
        super().__init__(*args, **kwargs)
        self.pydantic_type = pydantic_type
        self.adapter = TypeAdapter(pydantic_type)

    @property
    def python_type(self) -> type:
        """Return the Python type this column deals with (for introspection)."""
        return self.pydantic_type

    def load_dialect_impl(self, dialect: sa.engine.Dialect) -> sa.types.TypeEngine:
        # Use JSONB on Postgres, else plain JSON
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(sa.JSON())

    def process_bind_param(self, value: Any, dialect: sa.engine.Dialect) -> Any:
        """
        Convert Python value to a bindable SQL value:
         - None → NULL
         - Pydantic model → dict via model_dump()
         - dict → as-is (assumed already serialized)
        """
        if value is None:
            return None

        if isinstance(value, self.pydantic_type):
            return encrypt_sensitive_fields(value.model_dump())

        if isinstance(value, dict):
            return encrypt_sensitive_fields(value)

        raise TypeError(f"Expected {self.pydantic_type} or dict, got {type(value)}")

    def process_result_value(self, value: Any, dialect: sa.engine.Dialect) -> Any:
        """
        Convert loaded SQL value back into Python:
         - NULL → None
         - dict → Pydantic model via TypeAdapter.validate_python()
        """
        if value is None:
            return None

        # Pydantic v2 entry point
        return self.adapter.validate_python(decrypt_sensitive_fields(value))
        # For Pydantic v1, you could use:
        # return parse_obj_as(self.pydantic_type, value)
