from sqlalchemy import ForeignKeyConstraint
from sqlmodel import SQLModel


def has_relation(from_model: type[SQLModel], to_model: type[SQLModel]) -> bool:
    for rel in from_model.__mapper__.relationships.values():
        if rel.mapper.class_ is to_model:
            return True
    return False


def get_relations(model: type[SQLModel]) -> list[type[SQLModel]]:
    return [rel.mapper.class_ for rel in model.__mapper__.relationships.values()]


def get_fk_fields(from_model: type[SQLModel], to_model: type[SQLModel]) -> list[str]:
    fields = []
    for rel in from_model.__mapper__.relationships.values():
        if rel.mapper.class_ is to_model:
            for col in rel.local_columns:
                fields.append(col.name)
    return fields


def get_fk_to_remote_mapping(from_model: type[SQLModel], to_model: type[SQLModel]) -> dict[str, str]:
    mapping = {}

    from_table = from_model.__table__
    to_table = to_model.__table__

    # Проверяем ForeignKeyConstraint'ы у таблицы
    for constraint in from_table.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                local_col = element.parent
                remote_col = element.column
                if remote_col.table.name == to_table.name:
                    mapping[local_col.name] = remote_col.name

    return mapping


def get_pk_fields(model: type[SQLModel]) -> list[str]:
    """
    Get primary key fields of the model.
    """
    return [col.name for col in model.__table__.primary_key.columns]
