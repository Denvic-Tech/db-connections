import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute

from ..application.ownership import ConnectionOwnershipResolver
from ..application.public_projection import BrokenPublicConnectionView
from ..application.uow import ConnectionUnitOfWorkDependency, ConnectionUnitOfWorkFactory
from ..domain.entities import ConnectionCheckResult, ConnectionListQuery
from ..errors import ErrorMapper, ValidationFailedError
from ..fastapi.mapper import APIMapper, APISchemaSet, DefaultAPIMapper
from ..fastapi.schema_builders import (
    build_connection_create_model,
    build_connection_kind_type,
    build_connection_read_model,
    build_connection_update_model,
)
from ..fastapi.schemas import (
    BrokenConnectionReadResponse,
    ConnectionDriverInfoResponse,
    ConnectionKindInfoResponse,
    ConnectionTypeInfoResponse,
)
from ..registry.base import ConnectionRegistry
from ..registry.defaults import build_default_registry
from ..runtime.encryption import EncryptionProvider, NoOpEncryptionProvider
from ..runtime.settings import (
    DBConnectionRuntime,
    DBConnectionSettings,
    DBConnectionSettingsPatch,
)
from .schema_builders import build_connection_type_type

if TYPE_CHECKING:
    from db_connection.fastapi.builder import DBConnectionExtensionBuilder


CHECK_BODY_DEFAULT = Body(default=None)
TYPE_QUERY = Query(alias="type")
LOGGER = logging.getLogger(__name__)


class DBConnectionExtension:
    @classmethod
    def builder(cls) -> "DBConnectionExtensionBuilder":
        from db_connection.fastapi.builder import DBConnectionExtensionBuilder

        return DBConnectionExtensionBuilder()

    def __init__(
        self,
        *,
        uow_factory: ConnectionUnitOfWorkFactory,
        settings: DBConnectionSettings | None = None,
        registry: ConnectionRegistry | None = None,
        encryption_provider: EncryptionProvider | None = None,
        access_policy: Any = None,
        error_mapper: ErrorMapper | None = None,
        api_schemas: APISchemaSet | None = None,
        api_mapper: APIMapper | None = None,
        ownership_resolver: ConnectionOwnershipResolver | None = None,
        get_actor: Callable[..., Any] | None = None,
        get_uow: ConnectionUnitOfWorkDependency | None = None,
    ) -> None:
        self.runtime = DBConnectionRuntime(
            settings=settings or DBConnectionSettings(),
            registry=registry or build_default_registry(),
            uow_factory=uow_factory,
            encryption_provider=encryption_provider or NoOpEncryptionProvider(),
            access_policy=access_policy,
            ownership_resolver=ownership_resolver,
            error_mapper=error_mapper,
        )
        self._fallback_api_mapper = DefaultAPIMapper()
        self.api_schemas = api_schemas or APISchemaSet(
            create=build_connection_create_model(self.runtime.registry),
            read=build_connection_read_model(self.runtime.registry),
            update=build_connection_update_model(self.runtime.registry),
        )
        if self.api_schemas.broken_read is None:
            self.api_schemas.broken_read = BrokenConnectionReadResponse
        if self.api_schemas.connection_kind is None:
            self.api_schemas.connection_kind = build_connection_kind_type(self.runtime.registry)

        if self.api_schemas.connection_type is None:
            self.api_schemas.connection_type = build_connection_type_type(self.runtime.registry)

        self.api_mapper = api_mapper or self._fallback_api_mapper
        self.get_actor = get_actor or (lambda: None)
        self.get_uow = get_uow

    def build_router(
        self,
        *,
        prefix: str = "/db-connections",
        get_actor: Callable[..., Any] | None = None,
        get_uow: ConnectionUnitOfWorkDependency | None = None,
        tags: list[str] | None = None,
    ) -> APIRouter:
        resolved_get_actor = get_actor or self.get_actor
        resolved_get_uow = get_uow or self.get_uow or self._get_default_uow
        router_tags = ["DB Connections"] if tags is None else tags
        return self._build_router(
            prefix=prefix,
            get_actor=resolved_get_actor,
            get_uow=resolved_get_uow,
            tags=router_tags,
        )

    def install(
        self,
        target: FastAPI | APIRouter,
        *,
        prefix: str = "/db-connections",
        get_actor: Callable[..., Any] | None = None,
        get_uow: ConnectionUnitOfWorkDependency | None = None,
        tags: list[str] | None = None,
    ) -> APIRouter:
        router = self.build_router(
            prefix=prefix,
            get_actor=get_actor,
            get_uow=get_uow,
            tags=tags,
        )
        target.include_router(router)
        return router

    def update_settings(
        self,
        patch: DBConnectionSettingsPatch | dict[str, object] | None = None,
        /,
        **kwargs: object,
    ) -> DBConnectionSettings:
        payload: dict[str, object] = {}
        if patch is not None:
            payload.update(
                patch.model_dump(exclude_unset=True) if isinstance(patch, DBConnectionSettingsPatch) else patch
            )
        payload.update(kwargs)
        return self.runtime.update_settings(DBConnectionSettingsPatch.model_validate(payload))

    def _build_router(
        self,
        *,
        prefix: str,
        get_actor: Callable[..., Any],
        get_uow: ConnectionUnitOfWorkDependency,
        tags: list[str],
    ) -> APIRouter:
        router = APIRouter(
            prefix=prefix,
            tags=tags,
            route_class=self._build_route_class(),
        )
        create_schema = self.api_schemas.create
        read_schema = self.api_schemas.read
        broken_read_schema = self.api_schemas.broken_read
        read_response_schema = read_schema | broken_read_schema
        update_schema = self.api_schemas.update
        actor_dep = Depends(get_actor)
        uow_dep = Depends(get_uow)

        @router.get("/kinds", response_model=list[ConnectionKindInfoResponse])
        async def list_kinds() -> list[ConnectionKindInfoResponse]:
            return [
                ConnectionKindInfoResponse(
                    name=spec.name, description=spec.description, capabilities=list(spec.capabilities)
                )
                for spec in self.runtime.service.list_kinds()
            ]

        @router.get("/types", response_model=list[ConnectionTypeInfoResponse])
        async def list_types() -> list[ConnectionTypeInfoResponse]:
            return [
                ConnectionTypeInfoResponse(
                    name=spec.name,
                    kind=spec.kind,
                    default_driver=spec.default_driver,
                    drivers=[
                        ConnectionDriverInfoResponse(
                            name=driver_spec.name,
                            options_schema=driver_spec.options_model.model_json_schema(by_alias=False),
                            public_options_schema=(
                                None
                                if driver_spec.public_options_model is None
                                else driver_spec.public_options_model.model_json_schema(by_alias=False)
                            ),
                            tags=sorted(driver_spec.tags),
                        )
                        for driver_spec in spec.driver_specs
                    ],
                    supported_drivers=sorted(spec.supported_drivers),
                    capabilities=sorted(spec.capabilities),
                    tags=sorted(spec.tags),
                    properties_schema=spec.properties_model.model_json_schema(by_alias=False),
                    secrets_schema=(
                        None if spec.secrets_model is None else spec.secrets_model.model_json_schema(by_alias=False)
                    ),
                    public_schema=(
                        None if spec.public_model is None else spec.public_model.model_json_schema(by_alias=False)
                    ),
                )
                for spec in self.runtime.service.list_types()
            ]

        connection_kind_schema: type = self.api_schemas.connection_kind
        connection_type_schema: type = self.api_schemas.connection_type

        @router.get("", response_model=list[read_response_schema])  # type: ignore[valid-type]
        async def list_connections(
            kind: connection_kind_schema | None = None,  # type: ignore[valid-type]
            connection_type: Annotated[
                connection_type_schema | None,  # type: ignore[valid-type]
                TYPE_QUERY,
            ] = None,
            name: str | None = None,
            labels: str | None = None,
            metadata: str | None = None,
            extra: str | None = None,
            actor: Any = actor_dep,
            uow: Any = uow_dep,
        ) -> list[Any]:
            records = await self.runtime.service.list(
                ConnectionListQuery(
                    kind=kind,
                    type=connection_type,
                    name=name,
                    label_filters=self._parse_filter_param("labels", labels),
                    metadata_filters=self._parse_filter_param("metadata", metadata),
                    extra_filters=self._parse_filter_param("extra", extra),
                ),
                actor=actor,
                uow=uow,
            )
            return [
                self._build_read_response(
                    record=record,
                    read_schema=read_schema,
                    broken_read_schema=broken_read_schema,
                )
                for record in records
            ]

        @router.post("", response_model=read_schema)  # type: ignore[valid-type]
        async def create_connection(
            payload: create_schema,  # type: ignore[valid-type]
            actor: Any = actor_dep,
            uow: Any = uow_dep,
        ) -> Any:
            record = await self.runtime.service.create(
                self.api_mapper.to_create_draft(payload),
                actor=actor,
                uow=uow,
            )
            return self.api_mapper.to_response(
                read_schema,
                self.runtime.service.build_public_view(record),
            )

        @router.get("/{connection_id}", response_model=read_response_schema)  # type: ignore[valid-type]
        async def get_connection(
            connection_id: str,
            actor: Any = actor_dep,
            uow: Any = uow_dep,
        ) -> Any:
            record = await self.runtime.service.get(connection_id, actor=actor, uow=uow)
            return self._build_read_response(
                record=record,
                read_schema=read_schema,
                broken_read_schema=broken_read_schema,
            )

        @router.patch("/{connection_id}", response_model=read_response_schema)  # type: ignore[valid-type]
        async def update_connection(
            connection_id: str,
            payload: update_schema,  # type: ignore[valid-type]
            actor: Any = actor_dep,
            uow: Any = uow_dep,
        ) -> Any:
            record = await self.runtime.service.update(
                connection_id,
                self.api_mapper.to_patch(payload),
                actor=actor,
                uow=uow,
            )
            return self._build_read_response(
                record=record,
                read_schema=read_schema,
                broken_read_schema=broken_read_schema,
            )

        @router.delete("/{connection_id}", response_model=read_response_schema)  # type: ignore[valid-type]
        async def delete_connection(
            connection_id: str,
            actor: Any = actor_dep,
            uow: Any = uow_dep,
        ) -> Any:
            record = await self.runtime.service.delete(connection_id, actor=actor, uow=uow)
            return self._build_read_response(
                record=record,
                read_schema=read_schema,
                broken_read_schema=broken_read_schema,
            )

        @router.post("/check", response_model=ConnectionCheckResult)
        async def check_connection(
            payload: create_schema,  # type: ignore[valid-type]
            actor: Any = actor_dep,
        ) -> ConnectionCheckResult:
            return await self.runtime.service.check_payload(
                self.api_mapper.to_create_draft(payload),
                actor=actor,
            )

        @router.post("/{connection_id}/check", response_model=ConnectionCheckResult)
        async def check_stored_connection(
            connection_id: str,
            actor: Any = actor_dep,
            payload: update_schema | None = CHECK_BODY_DEFAULT,  # type: ignore[valid-type]
            uow: Any = uow_dep,
        ) -> ConnectionCheckResult:
            patch = None if payload is None else self.api_mapper.to_patch(payload)
            return await self.runtime.service.check_stored(
                connection_id,
                actor=actor,
                patch=patch,
                uow=uow,
            )

        return router

    def _build_route_class(self) -> type[APIRoute]:
        def to_http_exception(exc: Exception) -> HTTPException:
            return self._to_http_exception(self.runtime.error_mapper, exc)

        class TracebackLoggingRoute(APIRoute):
            def get_route_handler(self) -> Callable[[Request], Any]:
                original_handler = super().get_route_handler()
                route_name = self.name

                async def custom_route_handler(request: Request) -> Response:
                    try:
                        return await original_handler(request)
                    except (HTTPException, RequestValidationError):
                        LOGGER.exception("DB connection route '%s' failed.", route_name)
                        raise
                    except Exception as exc:
                        LOGGER.exception("DB connection route '%s' failed.", route_name)
                        raise to_http_exception(exc) from exc

                return custom_route_handler

        return TracebackLoggingRoute

    def _build_read_response(
        self,
        *,
        record,
        read_schema: Any,
        broken_read_schema: Any,
    ) -> Any:
        public_view = self.runtime.service.build_read_view(record)
        if isinstance(public_view, BrokenPublicConnectionView):
            broken_mapper = (
                getattr(self.api_mapper, "to_broken_response", None) or self._fallback_api_mapper.to_broken_response
            )
            return broken_mapper(broken_read_schema, public_view)
        return self.api_mapper.to_response(read_schema, public_view)

    def _to_http_exception(
        self,
        error_mapper: ErrorMapper,
        exc: Exception,
    ) -> HTTPException:
        spec = error_mapper.map_exception(exc)
        detail_payload = {
            "code": spec.code,
            "message": spec.message,
            "details": spec.details,
        }
        return HTTPException(
            status_code=spec.status_code,
            detail=detail_payload,
            headers=spec.headers,
        )

    def _parse_filter_param(self, field_name: str, raw_value: str | None) -> dict[str, Any]:
        if raw_value is None:
            return {}

        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ValidationFailedError(
                f"Query parameter '{field_name}' must contain valid JSON.",
                details={"parameter": field_name},
            ) from exc

        if not isinstance(parsed, dict):
            raise ValidationFailedError(
                f"Query parameter '{field_name}' must decode to a JSON object.",
                details={"parameter": field_name},
            )
        return parsed

    async def _get_default_uow(self) -> None:
        return None
