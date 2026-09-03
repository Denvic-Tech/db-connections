from typing import Any

from pydantic import create_model
from pydantic_core import PydanticUndefined
from pystructor.utils import get_fields
from sqlmodel import Column, Field, SQLModel
from sqlmodel.main import FieldInfo as SQLModelFieldInfo, SQLModelMetaclass

from db_connection.compat.sa_types import PydanticType


class DBConnectionMetaclass(SQLModelMetaclass):
    def __new__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        class_dict: dict[str, Any],
        **kwargs: Any
    ):
        # Проверяем, является ли класс таблицей
        is_table = kwargs.get("table", False) or "__tablename__" in class_dict

        if is_table:
            # Если поле connection_properties не определено в дочернем классе
            if "connection_properties" not in class_dict:
                # Ищем поле в базовом классе
                base = bases[0]
                fields_map = get_fields(base)
                if "connection_properties" in fields_map:
                    from db_connection.compat.models import ConnectionPropertiesType

                    ann, orig_fi = fields_map["connection_properties"]

                    # Создаём новый FieldInfo с новым sa_column
                    # Для SQLAlchemy используем Union тип
                    new_fi = Field(
                        default=orig_fi.default if orig_fi.default is not PydanticUndefined else ...,
                        sa_column=Column(PydanticType(ConnectionPropertiesType)),
                        description=orig_fi.description,
                        # Добавьте другие параметры, если нужно:
                        # alias=orig_fi.alias,
                        # title=orig_fi.title,
                    )

                    # Устанавливаем аннотацию
                    anns = class_dict.setdefault("__annotations__", {})
                    anns["connection_properties"] = ann

                    # Устанавливаем новое поле
                    class_dict["connection_properties"] = new_fi
            # Если поле connection_properties переопределено в дочернем классе
            else:
                fi = class_dict["connection_properties"]
                if hasattr(fi, "annotation"):  # Проверяем, что это FieldInfo
                    from db_connection.compat.models import ConnectionPropertiesType

                    ann = fi.annotation
                    # Создаём новый FieldInfo с новым sa_column
                    # Для SQLAlchemy используем Union тип
                    new_fi = Field(
                        default=fi.default if fi.default is not PydanticUndefined else ...,
                        sa_column=Column(PydanticType(ConnectionPropertiesType)),
                        description=fi.description,
                        # Добавьте другие параметры, если нужно
                    )
                    class_dict["connection_properties"] = new_fi

            if "type" not in class_dict:
                base = bases[0]
                fields_map = get_fields(base)

                if "type" in fields_map:
                    from sqlalchemy import Enum as SAEnum

                    from db_connection.compat.types import ConnectionType

                    ann, orig_fi = fields_map["type"]

                    new_fi = Field(
                        default=orig_fi.default if orig_fi.default is not PydanticUndefined else ...,
                        sa_column=Column(
                            SAEnum(
                                ConnectionType,
                                values_callable=lambda x: [e.value for e in x],
                                name='connectiontype'
                            )
                        ),
                        description=orig_fi.description,
                    )

                    anns = class_dict.setdefault("__annotations__", {})
                    anns["type"] = ann
                    class_dict["type"] = new_fi

        return super().__new__(cls, name, bases, class_dict, **kwargs)


class _DBConnectionMetaclass(SQLModelMetaclass):
    def __new__(
            cls,
            name: str,
            bases: tuple[type[Any], ...],
            class_dict: dict[str, Any],
            **kwargs: Any,
    ):

        fields = {
            name: (info.annotation, info)
            for name, info in class_dict.items()
            if isinstance(info, SQLModelFieldInfo)
        }

        if bases[0] is not SQLModel:
            fields = {**fields, **get_fields(bases[0])}

        model = create_model(
            f"{name}PydanticModel",
            __config__=class_dict.get('model_config', {}),
            **fields
        )

        obj = super().__new__(
            cls=cls,
            name=name,
            bases=bases,
            class_dict=class_dict,
            **kwargs
        )

        setattr(obj, '__pydantic_model', model)

        return obj

    def __init__(
            cls,
            classname: str,
            bases: tuple[type, ...],
            dict_: dict[str, Any],
            **kw: Any
    ) -> None:
        super().__init__(classname, bases, dict_, **kw)
