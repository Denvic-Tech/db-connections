from __future__ import annotations

from threading import RLock

from pydantic import BaseModel, ConfigDict

from ..application.ownership import ConnectionOwnershipResolver, NoOpConnectionOwnershipResolver
from ..application.policies import AccessPolicy, AllowAllAccessPolicy
from ..application.service import ConnectionService
from ..application.uow import ConnectionUnitOfWorkFactory
from ..errors import ErrorMapper
from ..registry.base import ConnectionRegistry
from ..runtime.encryption import EncryptionProvider

# pylint: disable=duplicate-code


class DBConnectionSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_connections: int | None = None


class DBConnectionSettingsPatch(BaseModel):
    max_connections: int | None = None


class DBConnectionRuntime:
    def __init__(
        self,
        *,
        settings: DBConnectionSettings,
        registry: ConnectionRegistry,
        uow_factory: ConnectionUnitOfWorkFactory,
        encryption_provider: EncryptionProvider,
        access_policy: AccessPolicy | None = None,
        ownership_resolver: ConnectionOwnershipResolver | None = None,
        error_mapper: ErrorMapper | None = None,
    ) -> None:
        self._lock = RLock()
        self._settings = settings
        self._registry = registry
        self._uow_factory = uow_factory
        self._encryption_provider = encryption_provider
        self._access_policy = access_policy or AllowAllAccessPolicy()
        self._ownership_resolver = ownership_resolver or NoOpConnectionOwnershipResolver()
        self._error_mapper = error_mapper or ErrorMapper()
        self._service = self._build_service(settings)

    def _build_service(self, settings: DBConnectionSettings) -> ConnectionService:
        return ConnectionService(
            settings=settings,
            registry=self._registry,
            uow_factory=self._uow_factory,
            access_policy=self._access_policy,
            ownership_resolver=self._ownership_resolver,
        )

    @property
    def settings(self) -> DBConnectionSettings:
        return self._settings

    @property
    def registry(self) -> ConnectionRegistry:
        return self._registry

    @property
    def uow_factory(self) -> ConnectionUnitOfWorkFactory:
        return self._uow_factory

    @property
    def encryption_provider(self) -> EncryptionProvider:
        return self._encryption_provider

    @property
    def access_policy(self) -> AccessPolicy:
        return self._access_policy

    @property
    def error_mapper(self) -> ErrorMapper:
        return self._error_mapper

    @property
    def service(self) -> ConnectionService:
        return self._service

    def update_settings(self, patch: DBConnectionSettingsPatch | dict[str, object]) -> DBConnectionSettings:
        patch_model = (
            patch if isinstance(patch, DBConnectionSettingsPatch) else DBConnectionSettingsPatch.model_validate(patch)
        )
        update_data = patch_model.model_dump(exclude_unset=True)
        with self._lock:
            self._settings = self._settings.model_copy(update=update_data)
            self._service = self._build_service(self._settings)
            return self._settings




