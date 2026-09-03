from datetime import datetime

from fastapi import Depends, HTTPException, Query
from sqlmodel import select

from db_connection.compat import (
    dependencies as deps,
    exceptions as exc,
    extension_config as ext_config,
)
from db_connection.compat.models import DBConnection as DatabaseConnectionModel
from db_connection.compat.types import ConnectionType


async def check_db_connection(
        db_connection: ext_config.DBConnectionCreateSchema,
        user: ext_config.GetUserDep,
        db_conn_manager: deps.ConnectionManager = Depends(deps.get_connection_manager)
):
    """
    Check database connection
    """
    return db_conn_manager.check_connection(db_connection)


async def check_db_connection_by_id(
        db_connection_id,
        db_connection_update: ext_config.DBConnectionUpdateSchema,
        user: ext_config.GetUserDep,
        session: deps.Session = Depends(deps.get_session),
        DBConnectionModel: type[DatabaseConnectionModel] = Depends(deps.get_db_connection_model),
        db_conn_manager: deps.ConnectionManager = Depends(deps.get_connection_manager)
):
    """
    Check database connection by id
    """
    statement = select(DBConnectionModel).where(
        DBConnectionModel.id == db_connection_id,
        DBConnectionModel.is_deleted == False
    )

    if ext_config.USE_AUTH and not ext_config.disable_pk_filtration(user):
        statement = statement.where(
            *[getattr(DBConnectionModel, fk) == getattr(user, pk)
              for fk, pk in ext_config.db_connection_to_user_fks_mapping.items()]
        )

    db_conn = session.exec(statement).first()

    if not db_conn:
        raise exc.DBConnectionNotFound(connection_id=db_connection_id)

    update_data = db_connection_update.model_dump(exclude_unset=True)

    if getattr(db_connection_update, "connection_properties", None) is not None:
        update_data["connection_properties"] = db_connection_update.connection_properties

    db_conn = db_conn.sqlmodel_update(update_data)

    return db_conn_manager.check_connection(db_conn)


async def get_db_connections(
        user: ext_config.GetUserDep,
        session: deps.Session = Depends(deps.get_session),
        filters: ext_config.filters_model = Depends(),
        connection_type: ConnectionType | None = Query(
            default=None,
            description="Optional connection type filter",
        ),
        db_conn_manager: deps.ConnectionManager = Depends(deps.get_connection_manager)
):
    """
    Get all database connections
    """
    db_conns = db_conn_manager.get_db_connections(user, session, connection_type, filters)
    if db_conn_manager.MAX_CONNECTIONS is not None:
        # Возвращаем не больше MAX_CONNECTIONS соединений
        return db_conns[:db_conn_manager.MAX_CONNECTIONS]
    else:
        return db_conns


async def get_db_connection(
        user: ext_config.GetUserDep,
        session: deps.Session = Depends(deps.get_session),
        DBConnectionModel: type[DatabaseConnectionModel] = Depends(deps.get_db_connection_model),
        **kwargs,
):
    """
    Get all database connections
    """
    statement = select(DBConnectionModel).where(
        DBConnectionModel.is_deleted == False
    )
    statement = statement.where(
        *[getattr(DBConnectionModel, field_name) == kwargs.get(field_name)
          for field_name in ext_config.db_connection_pks]
    )

    if ext_config.disable_pk_filtration(user):
        db_conn = session.exec(statement).first()

        if not db_conn:
            raise exc.DBConnectionNotFound(**kwargs)

        return db_conn

    if ext_config.USE_AUTH:
        statement = statement.where(
            *[getattr(DBConnectionModel, fk) == getattr(user, pk)
              for fk, pk in ext_config.db_connection_to_user_fks_mapping.items()]
        )

    db_conn = session.exec(statement).first()

    if not db_conn:
        raise exc.DBConnectionNotFound(**kwargs)

    return db_conn


async def create_db_connection(
        db_connection: ext_config.DBConnectionCreateSchema,
        user: ext_config.GetUserDep,
        session: deps.Session = Depends(deps.get_session),
        DBConnectionModel: type[DatabaseConnectionModel] = Depends(deps.get_db_connection_model),
        db_conn_manager: deps.ConnectionManager = Depends(deps.get_connection_manager)
):
    """
    Create database connection
    """
    if db_conn_manager.validate_max_connections(user, session):
        if ext_config.USE_AUTH:
            db_conn = DBConnectionModel(**{
                **db_connection.model_dump(),
                "connection_properties": db_connection.connection_properties,
                **{
                    fk: getattr(user, pk)
                    for fk, pk in ext_config.db_connection_to_user_fks_mapping.items()
                }
            })
        else:
            db_conn = DBConnectionModel.model_validate(db_connection)

        session.add(db_conn)
        session.commit()
        session.refresh(db_conn)

        return db_conn
    else:
        raise HTTPException(status_code=405, detail="Database connections more than allowed, use delete endpoint.")


async def update_db_connection(
        db_connection_update: ext_config.DBConnectionUpdateSchema,
        user: ext_config.GetUserDep,
        session: deps.Session = Depends(deps.get_session),
        DBConnectionModel: type[DatabaseConnectionModel] = Depends(deps.get_db_connection_model),
        db_conn_manager: deps.ConnectionManager = Depends(deps.get_connection_manager),
        **kwargs,
):
    """
    Update database connection
    """
    if db_conn_manager.validate_max_connections(user, session):
        statement = select(DBConnectionModel).where(
            DBConnectionModel.is_deleted == False
        )
        statement = statement.where(
            *[getattr(DBConnectionModel, field_name) == kwargs.get(field_name)
              for field_name in ext_config.db_connection_pks]
        )

        if ext_config.USE_AUTH and not ext_config.disable_pk_filtration(user):
            statement = statement.where(
                *[getattr(DBConnectionModel, fk) == getattr(user, pk)
                  for fk, pk in ext_config.db_connection_to_user_fks_mapping.items()]
            )

        db_conn = session.exec(statement).first()

        if not db_conn:
            raise exc.DBConnectionNotFound(**kwargs)

        update_data = db_connection_update.model_dump(exclude_unset=True)

        if getattr(db_connection_update, "connection_properties", None) is not None:
            update_data["connection_properties"] = db_connection_update.connection_properties

        db_conn = db_conn.sqlmodel_update(update_data)
        db_conn.updated_at = datetime.now()

        session.add(db_conn)
        session.commit()
        session.refresh(db_conn)

        return db_conn
    else:
        raise HTTPException(status_code=405, detail="Database connections more than allowed, use delete endpoint.")


async def upsert_db_connection(
        db_connection: ext_config.DBConnectionUpsertSchema,
        user: ext_config.GetUserDep,
        session: deps.Session = Depends(deps.get_session),
        DBConnectionModel: type[DatabaseConnectionModel] = Depends(deps.get_db_connection_model),
        db_conn_manager: deps.ConnectionManager = Depends(deps.get_connection_manager),
):
    """
    Upsert database connection
    """
    if db_conn_manager.validate_max_connections(user, session):
        if ext_config.USE_AUTH:
            db_conn = DBConnectionModel(
                **db_connection.model_dump(),
                **{
                    fk: getattr(user, pk)
                    for fk, pk in ext_config.db_connection_to_user_fks_mapping.items()
                }
            )
        else:
            db_conn = DBConnectionModel.model_validate(db_connection)

        statement = select(DBConnectionModel).where(
            DBConnectionModel.is_deleted == False
        )

        statement = statement.where(
            *[getattr(DBConnectionModel, field_name) == getattr(db_conn, field_name)
              for field_name in ext_config.db_connection_pks]
        )

        existing_db_conn = session.exec(statement).first()

        if existing_db_conn:
            db_conn = existing_db_conn.sqlmodel_update(db_conn.model_dump(exclude={"id"},
                                                                          exclude_unset=True))
            db_conn.updated_at = datetime.now()
        else:
            db_conn.created_at = datetime.now()

        session.add(db_conn)
        session.commit()
        session.refresh(db_conn)

        return db_conn
    else:
        raise HTTPException(status_code=405, detail="Database connections more than allowed, use delete endpoint.")


async def delete_db_connection(
        user: ext_config.GetUserDep,
        session: deps.Session = Depends(deps.get_session),
        DBConnectionModel: type[DatabaseConnectionModel] = Depends(deps.get_db_connection_model),
        **kwargs,
):
    """
    Delete database connection
    """
    statement = select(DBConnectionModel).where(
        DBConnectionModel.is_deleted == False
    )
    statement = statement.where(
        *[getattr(DBConnectionModel, field_name) == kwargs.get(field_name)
          for field_name in ext_config.db_connection_pks]
    )

    if ext_config.USE_AUTH and not ext_config.disable_pk_filtration(user):
        statement = statement.where(
            *[getattr(DBConnectionModel, fk) == getattr(user, pk)
              for fk, pk in ext_config.db_connection_to_user_fks_mapping.items()]
        )

    db_conn = session.exec(statement).first()

    if not db_conn:
        raise exc.DBConnectionNotFound(**kwargs)

    db_conn.is_deleted = True
    session.add(db_conn)
    session.commit()
    session.refresh(db_conn)

    return db_conn
