from inspect import Parameter
from typing import Any

import sqlmodel as sa
from fastapi import Path
from sqlalchemy.sql import sqltypes

from db_connection.compat.utils import sa as sa_utils


def try_get_hint(_type: sqltypes.TypeEngine[Any]) -> type[Any]:
    if hasattr(_type, 'impl'):
        return try_get_hint(_type.impl)

    try:
        return _type.python_type
    except NotImplementedError:
        return Any


def pks_func_parameters(
        model: type[sa.SQLModel],
) -> list[Parameter]:
    pk_fields = sa_utils.get_pk_fields(model)

    hints = {}
    for field_name in pk_fields:
        field = getattr(model, field_name)
        hints[field_name] = try_get_hint(field.type)

    param_types = {}
    for field_name in pk_fields:
        param_types[field_name] = Path(..., description=f"{field_name} of {model.__name__}")

    return [
        Parameter(
            name=field_name,
            kind=Parameter.KEYWORD_ONLY,
            default=param_types[field_name],
            annotation=hints[field_name],
        )
        for field_name in pk_fields
    ]


def sort_parameters(parameters: list[Parameter]) -> list[Parameter]:
    kind_order = {
        Parameter.POSITIONAL_ONLY: 0,
        Parameter.POSITIONAL_OR_KEYWORD: 1,
        Parameter.VAR_POSITIONAL: 2,  # *args
        Parameter.KEYWORD_ONLY: 3,
        Parameter.VAR_KEYWORD: 4      # **kwargs
    }
    return sorted(parameters, key=lambda p: kind_order[p.kind])
