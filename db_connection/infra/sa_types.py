from __future__ import annotations

from importlib import import_module
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB

from ..domain.drivers import DriverOptionsBase


class DriverOptionsType(sa.types.TypeDecorator):  # pylint: disable=too-many-ancestors
    impl = sa.types.JSON
    cache_ok = True

    @property
    def python_type(self) -> type:
        return DriverOptionsBase

    def load_dialect_impl(self, dialect: sa.engine.Dialect) -> sa.types.TypeEngine:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(sa.JSON())

    def process_bind_param(self, value: Any, _dialect: sa.engine.Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, DriverOptionsBase):
            raise TypeError(f"Expected DriverOptionsBase, got {type(value)}")
        model_type = type(value)
        return {
            "model_ref": f"{model_type.__module__}:{model_type.__qualname__}",
            "data": value.model_dump(mode="json"),
        }

    def process_result_value(self, value: Any, _dialect: sa.engine.Dialect) -> DriverOptionsBase | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError(f"Expected JSON object for driver options, got {type(value)}")

        model_ref = value.get("model_ref")
        data = value.get("data")
        if not isinstance(model_ref, str):
            raise TypeError("Driver options payload is missing model_ref.")

        model_type = _resolve_model_ref(model_ref)
        if not issubclass(model_type, DriverOptionsBase):
            raise TypeError(f"{model_ref} is not a DriverOptionsBase subtype.")
        return TypeAdapter(model_type).validate_python(data)

    def process_literal_param(self, value: Any, _dialect: sa.engine.Dialect) -> str | None:
        if value is None:
            return None
        raise NotImplementedError("Literal rendering is not supported for DriverOptionsType.")


def _resolve_model_ref(model_ref: str) -> type[BaseModel]:
    module_name, _, attribute_path = model_ref.partition(":")
    if not module_name or not attribute_path:
        raise TypeError(f"Invalid model_ref '{model_ref}'.")

    module = import_module(module_name)
    current: Any = module
    for attribute in attribute_path.split("."):
        current = getattr(current, attribute)
    if not isinstance(current, type) or not issubclass(current, BaseModel):
        raise TypeError(f"{model_ref} does not resolve to a Pydantic model.")
    return current
