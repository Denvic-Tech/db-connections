from collections.abc import Callable
from enum import Enum
from inspect import Signature, signature
from typing import Annotated, Any, TypeVar

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends
from fastapi.datastructures import Default
from makefun import create_function
from sqlalchemy import Engine
from sqlmodel import SQLModel

from db_connection.compat import extension_config as ext_config, types
from db_connection.compat.models import DBConnection as DBConnectionModel
from db_connection.compat.schemas import ConnectionStatus
from db_connection.compat.signature_builder import pks_func_parameters, sort_parameters
from db_connection.compat.utils import create_filters_class, sa as sa_utils

DBConnectionModelT = TypeVar("DBConnectionModelT", bound=DBConnectionModel)
UserModelT = TypeVar("UserModelT", bound=SQLModel)


class DBConnectionAPIRouter(APIRouter):
    def __init__(
            self,

            engine: Engine,
            db_connection_model: type[DBConnectionModelT],
            db_connection_create_schema: type[type[DBConnectionModelT]],
            db_connection_read_schema: type[type[DBConnectionModelT]],
            db_connection_update_schema: type[type[DBConnectionModelT]],
            db_connection_upsert_schema: type[type[DBConnectionModelT]],

            user_model: type[UserModelT] | None = None,
            get_user_dependency: Callable[[...], UserModelT | None] | None = None,

            disable_pk_filtration: Callable | None = lambda user: False,
            fernet_key: str | bytes | Fernet | None = None,

            prefix: str | None = "/db-connections",
            tags: list[str | Enum] | None = None,

            max_connections: int | None = None,

            filters: list[Any] | None = None,

            *args,
            **kwargs
    ):
        """
        FastAPI APIRouter для работы с соединениями с БД
        :param get_session_dependency: Dependency для получения БД сессии
        :param db_connection_model: Модель соединения с БД
        :param db_connection_create_schema: Схема для создания соединения с БД
        :param db_connection_read_schema: Схема для чтения соединения с БД
        :param db_connection_update_schema: Схема для обновления соединения с БД
        :param db_connection_upsert_schema: Схема для создания/обновления соединения с БД

        :param prefix: Префикс для маршрутов
        :param tags: Теги для маршрутов

        :param user_model: Модель пользователя, если требуется авторизация
        :param get_user_dependency: Функция для получения пользователя, если требуется авторизация
        :param disable_pk_filtration: Функция, возвращающая bool, и в путях отключается фильтрация по ПК для User
        :param filters:
        """
        if filters is None:
            filters = []
        ext_config.engine = engine
        ext_config.DBConnectionModel = db_connection_model
        ext_config.DBConnectionCreateSchema = db_connection_create_schema
        ext_config.DBConnectionReadSchema = db_connection_read_schema
        ext_config.DBConnectionUpdateSchema = db_connection_update_schema
        ext_config.DBConnectionUpsertSchema = db_connection_upsert_schema
        ext_config.UserModel = user_model
        ext_config.disable_pk_filtration = disable_pk_filtration
        ext_config.max_connections = max_connections
        ext_config.filters = filters
        ext_config.filters_model = create_filters_class(model_class=db_connection_model, filter_fields=filters)

        if isinstance(fernet_key, Fernet):
            self.fernet = fernet_key
        elif fernet_key:
            key_value = fernet_key.encode("utf-8") if isinstance(fernet_key, str) else fernet_key
            self.fernet = Fernet(key_value)
        else:
            self.fernet = None

        ext_config.fernet = self.fernet

        self.pk_fields = sa_utils.get_pk_fields(db_connection_model)
        ext_config.db_connection_pks = self.pk_fields

        if get_user_dependency and user_model:
            ext_config.GetUserDep = Annotated[user_model | None | types.UndefinedType, Depends(get_user_dependency)]
            ext_config.db_connection_to_user_fks_mapping = sa_utils.get_fk_to_remote_mapping(db_connection_model,
                                                                                             user_model)
            ext_config.USE_AUTH = True
        else:
            if get_user_dependency and not user_model:
                raise ValueError("'get_user_dependency' provided without 'user_model'.")
            if not get_user_dependency and user_model:
                raise ValueError("'user_model' provided without 'get_user_dependency'.")

        if tags is None:
            tags = ["DB Connections"]

        self.pks_func_parameters = pks_func_parameters(db_connection_model)
        self.pks_path = "/" + "/".join(f"{{{field_name}}}" for field_name in self.pk_fields)

        super().__init__(
            *args,
            prefix=prefix,
            tags=tags,
            **kwargs
        )

        self.add_db_conn_routes()

    @staticmethod
    def validate_models():
        if not issubclass(ext_config.DBConnectionModel, DBConnectionModel):
            raise TypeError(f"{ext_config.DBConnectionModel} is not a subclass of {DBConnectionModel}")

    def add_db_conn_routes(self):
        self.validate_models()

        from . import routes

        self.add_api_route(
            "/check-connection",
            routes.check_db_connection,
            response_model=ConnectionStatus,
            methods=["POST"],
        )

        self.add_api_route(
            "/check-connection/{db_connection_id}",
            routes.check_db_connection_by_id,
            response_model=ConnectionStatus,
            methods=["POST"],
        )

        self.add_api_route(
            "",
            routes.get_db_connections,
            response_model=list[ext_config.DBConnectionReadSchema],
            methods=["GET"],
        )

        self.add_api_pks_route(
            routes.get_db_connection,
            response_model=ext_config.DBConnectionReadSchema,
            methods=["GET"],
        )

        self.add_api_route(
            "",
            routes.create_db_connection,
            response_model=ext_config.DBConnectionReadSchema,
            methods=["POST"],
        )

        self.add_api_pks_route(
            routes.update_db_connection,
            response_model=ext_config.DBConnectionReadSchema,
            methods=["PATCH"],
        )

        self.add_api_route(
            "",
            routes.upsert_db_connection,
            response_model=ext_config.DBConnectionReadSchema,
            methods=["PUT"],
        )

        self.add_api_pks_route(
            routes.delete_db_connection,
            response_model=ext_config.DBConnectionReadSchema,
            methods=["DELETE"],
        )

    def add_api_pks_route(
            self,
            endpoint: Callable[..., Any],
            response_model: Any = Default(None),
            methods: list[str] | None = None
    ):
        """
        Adds a route that requires primary keys in the path.
        :param endpoint: The endpoint function to be called.
        :param response_model: The response model for the endpoint.
        :param methods: The HTTP methods for the route.
        """
        orig_signature = signature(endpoint)
        orig_parameters = [parameter
                           for parameter in orig_signature.parameters.values()
                           if parameter.name != "kwargs"]

        parameters = sort_parameters([
            *self.pks_func_parameters,
            *orig_parameters,
        ])

        self.add_api_route(
            self.pks_path,
            create_function(
                func_signature=Signature(parameters=parameters),
                func_impl=endpoint,
                func_name=endpoint.__name__,
                doc=endpoint.__doc__,
            ),
            response_model=response_model,
            methods=methods,
        )
