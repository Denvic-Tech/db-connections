from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..application.ownership import ConnectionOwnershipResolver
from ..application.uow import ConnectionUnitOfWorkDependency, ConnectionUnitOfWorkFactory
from ..domain.specs import KindSpec, TypeSpec
from ..dsl import (
    DBConnectionDSLConfig,
    apply_dsl_registry,
    apply_dsl_settings,
    load_dsl_data,
    load_dsl_file,
)
from ..errors import ErrorMapper, ValidationFailedError
from ..fastapi.mapper import APIMapper, APISchemaSet
from ..plugins import DEFAULT_PLUGIN_GROUP, load_registry_plugins
from ..registry.base import ConnectionRegistry
from ..registry.defaults import build_default_registry
from ..runtime.encryption import EncryptionProvider
from ..runtime.settings import DBConnectionSettings

if TYPE_CHECKING:
    from db_connection.fastapi.extension import DBConnectionExtension


@dataclass(slots=True)
class PluginEntryPointRequest:
    group: str
    names: tuple[str, ...] | None = None


class DBConnectionExtensionBuilder:
    def __init__(self) -> None:
        self._uow_factory: ConnectionUnitOfWorkFactory | None = None
        self._settings: DBConnectionSettings | None = None
        self._max_connections: int | None = None
        self._max_connections_set = False
        self._registry: ConnectionRegistry | None = None
        self._use_default_types = True
        self._kinds: list[KindSpec] = []
        self._types: list[TypeSpec] = []
        self._encryption_provider: EncryptionProvider | None = None
        self._access_policy: Any = None
        self._error_mapper: ErrorMapper | None = None
        self._api_schemas: APISchemaSet | None = None
        self._api_mapper: APIMapper | None = None
        self._ownership_resolver: ConnectionOwnershipResolver | None = None
        self._get_actor: Callable[..., Any] | None = None
        self._get_uow: ConnectionUnitOfWorkDependency | None = None
        self._dsl_configs: list[DBConnectionDSLConfig] = []
        self._plugin_requests: list[PluginEntryPointRequest] = []

    def with_uow_factory(
        self,
        uow_factory: ConnectionUnitOfWorkFactory,
    ) -> DBConnectionExtensionBuilder:
        self._uow_factory = uow_factory
        return self

    def with_settings(self, settings: DBConnectionSettings) -> DBConnectionExtensionBuilder:
        self._settings = settings
        return self

    def with_max_connections(self, max_connections: int | None) -> DBConnectionExtensionBuilder:
        self._max_connections = max_connections
        self._max_connections_set = True
        return self

    def with_registry(self, registry: ConnectionRegistry) -> DBConnectionExtensionBuilder:
        self._registry = registry.copy()
        return self

    def with_default_types(self, enabled: bool = True) -> DBConnectionExtensionBuilder:
        self._use_default_types = enabled
        return self

    def with_kind(self, spec: KindSpec) -> DBConnectionExtensionBuilder:
        self._kinds.append(spec)
        return self

    def with_type(self, spec: TypeSpec) -> DBConnectionExtensionBuilder:
        self._types.append(spec)
        return self

    def with_encryption_provider(
        self,
        encryption_provider: EncryptionProvider,
    ) -> DBConnectionExtensionBuilder:
        self._encryption_provider = encryption_provider
        return self

    def with_access_policy(self, access_policy: Any) -> DBConnectionExtensionBuilder:
        self._access_policy = access_policy
        return self

    def with_error_mapper(self, error_mapper: ErrorMapper) -> DBConnectionExtensionBuilder:
        self._error_mapper = error_mapper
        return self

    def with_api_schemas(self, api_schemas: APISchemaSet) -> DBConnectionExtensionBuilder:
        self._api_schemas = api_schemas
        return self

    def with_api_mapper(self, api_mapper: APIMapper) -> DBConnectionExtensionBuilder:
        self._api_mapper = api_mapper
        return self

    def with_ownership_resolver(
        self,
        ownership_resolver: ConnectionOwnershipResolver,
    ) -> DBConnectionExtensionBuilder:
        self._ownership_resolver = ownership_resolver
        return self

    def with_actor_dependency(
        self,
        get_actor: Callable[..., Any],
    ) -> DBConnectionExtensionBuilder:
        self._get_actor = get_actor
        return self

    def with_uow_dependency(
        self,
        get_uow: ConnectionUnitOfWorkDependency,
    ) -> DBConnectionExtensionBuilder:
        self._get_uow = get_uow
        return self

    def with_plugin_entrypoints(
        self,
        names: Iterable[str] | None = None,
        *,
        group: str = DEFAULT_PLUGIN_GROUP,
    ) -> DBConnectionExtensionBuilder:
        self._plugin_requests.append(
            PluginEntryPointRequest(
                group=group,
                names=None if names is None else tuple(names),
            )
        )
        return self

    def with_dsl_data(
        self,
        data: Mapping[str, Any] | DBConnectionDSLConfig,
    ) -> DBConnectionExtensionBuilder:
        config = data if isinstance(data, DBConnectionDSLConfig) else load_dsl_data(data)
        self._dsl_configs.append(config)
        return self

    def with_dsl_file(self, path: str | Path) -> DBConnectionExtensionBuilder:
        self._dsl_configs.append(load_dsl_file(path))
        return self

    def build(self) -> DBConnectionExtension:
        if self._uow_factory is None:
            raise ValidationFailedError("Unit of work factory is required to build DBConnectionExtension.")

        settings = self._build_settings()
        registry = self._build_registry()

        from db_connection.fastapi.extension import DBConnectionExtension

        return DBConnectionExtension(
            uow_factory=self._uow_factory,
            settings=settings,
            registry=registry,
            encryption_provider=self._encryption_provider,
            access_policy=self._access_policy,
            error_mapper=self._error_mapper,
            api_schemas=self._api_schemas,
            api_mapper=self._api_mapper,
            ownership_resolver=self._ownership_resolver,
            get_actor=self._get_actor,
            get_uow=self._get_uow,
        )

    def _build_settings(self) -> DBConnectionSettings:
        settings = DBConnectionSettings()
        for config in self._dsl_configs:
            settings = apply_dsl_settings(settings, config)
        if self._settings is not None:
            settings = self._settings
        if self._max_connections_set:
            settings = settings.model_copy(update={"max_connections": self._max_connections})
        return settings

    def _build_registry(self) -> ConnectionRegistry:
        registry = build_default_registry() if self._use_default_types else ConnectionRegistry()
        if self._registry is not None:
            self._merge_registry(registry, self._registry)
        for config in self._dsl_configs:
            apply_dsl_registry(registry, config)
        for plugin_request in self._plugin_requests_from_dsl():
            load_registry_plugins(
                registry,
                group=plugin_request.group,
                names=plugin_request.names,
            )
        for plugin_request in self._plugin_requests:
            load_registry_plugins(
                registry,
                group=plugin_request.group,
                names=plugin_request.names,
            )
        for kind in self._kinds:
            registry.register_kind(kind)
        for connection_type in self._types:
            registry.register_type(connection_type)
        return registry

    def _plugin_requests_from_dsl(self) -> list[PluginEntryPointRequest]:
        return [
            PluginEntryPointRequest(group=plugin.group, names=(plugin.name,))
            for config in self._dsl_configs
            for plugin in config.plugins
        ]

    def _merge_registry(self, target: ConnectionRegistry, source: ConnectionRegistry) -> None:
        for kind in source.list_kinds():
            target.register_kind(kind, overwrite=True)
        for connection_type in source.list_types():
            target.register_type(connection_type, overwrite=True)




