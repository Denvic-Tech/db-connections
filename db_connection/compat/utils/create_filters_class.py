from typing import Any

from pydantic import Field, create_model

from db_connection.compat.models import DBConnectionBaseFilters, TModel


def create_filters_class(
        model_class: type[TModel],
        filter_fields: list[str],
        class_name_suffix: str = "Filters"
) -> type[DBConnectionBaseFilters[TModel]]:
    """
    Создает класс фильтров, наследующийся от DBConnectionBaseFilters.
    """
    field_definitions = {
        field_name: (Any | None, Field(default=None, description=f"Фильтр по полю '{field_name}'"))
        for field_name in filter_fields
    }

    class_name = f"{model_class.__name__}{class_name_suffix}"

    return create_model(
        class_name,
        __base__=DBConnectionBaseFilters[TModel],  # type: ignore
        **field_definitions
    )
