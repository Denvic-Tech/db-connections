from .application.ownership import ConnectionOwnershipResolver, NoOpConnectionOwnershipResolver
from .application.policies import AccessContext, AccessPolicy, AllowAllAccessPolicy
from .application.uow import ConnectionUnitOfWork, ConnectionUnitOfWorkDependency, ConnectionUnitOfWorkFactory
from .connectors import Connector
from .domain import ConnectionPatch, ConnectionRecord, StoredConnectionIssue, ValidatedConnection
from .domain.drivers import DriverOptionsBase, DriverSpec, NoDriverOptions, ODBCDriverOptions
from .domain.entities.check_result import ConnectionCheckResult
from .domain.entities.draft import ConnectionDraft
from .domain.entities.list_query import ConnectionListQuery
from .domain.repositories import ConnectionRepository
from .domain.specs import KindSpec, TypeSpec
from .dsl import (
    DBConnectionDSLConfig,
    apply_dsl_registry,
    apply_dsl_settings,
    load_dsl_data,
    load_dsl_file,
)
from .errors import (
    AccessDeniedError,
    ConnectionLimitExceededError,
    ConnectionNotFoundError,
    ConnectionTypeNotSupportedError,
    DBConnectionError,
    ErrorMapper,
    ErrorResponseSpec,
    InfrastructureError,
    SecretDecryptionError,
    ValidationFailedError,
)
from .fastapi.builder import DBConnectionExtensionBuilder
from .fastapi.extension import APISchemaSet, DBConnectionExtension
from .fastapi.mapper import DefaultAPIMapper
from .fastapi.schema_builders import (
    build_connection_create_model,
    build_connection_read_model,
    build_connection_update_model,
)
from .fastapi.schemas import (
    BrokenConnectionReadResponse,
    ConnectionCreateRequest,
    ConnectionDriverInfoResponse,
    ConnectionIssueResponse,
    ConnectionReadResponse,
    ConnectionTypeInfoResponse,
    ConnectionUpdateRequest,
)
from .infra.models import DefaultStoredConnection
from .infra.record_mapper import StoredConnectionRecordMapper
from .infra.repositories import DefaultSQLModelConnectionRepository
from .infra.unit_of_work import (
    DefaultSQLModelConnectionUnitOfWork,
    DefaultSQLModelConnectionUnitOfWorkFactory,
)
from .plugins import DEFAULT_PLUGIN_GROUP, load_registry_plugins
from .registry.base import ConnectionRegistry
from .registry.defaults import build_default_registry
from .runtime.encryption import (
    EncryptionProvider,
    FernetEncryptionProvider,
    NoOpEncryptionProvider,
)
from .runtime.settings import DBConnectionRuntime, DBConnectionSettings, DBConnectionSettingsPatch

__all__ = [
    "DEFAULT_PLUGIN_GROUP",
    "APISchemaSet",
    "AccessContext",
    "AccessDeniedError",
    "AccessPolicy",
    "AllowAllAccessPolicy",
    "BrokenConnectionReadResponse",
    "ConnectionCheckResult",
    "ConnectionCreateRequest",
    "ConnectionDraft",
    "ConnectionDriverInfoResponse",
    "ConnectionIssueResponse",
    "ConnectionLimitExceededError",
    "ConnectionListQuery",
    "ConnectionNotFoundError",
    "ConnectionOwnershipResolver",
    "ConnectionPatch",
    "ConnectionReadResponse",
    "ConnectionRecord",
    "ConnectionRegistry",
    "ConnectionRepository",
    "ConnectionTypeInfoResponse",
    "ConnectionTypeNotSupportedError",
    "ConnectionUnitOfWork",
    "ConnectionUnitOfWorkDependency",
    "ConnectionUnitOfWorkFactory",
    "ConnectionUpdateRequest",
    "Connector",
    "DBConnectionDSLConfig",
    "DBConnectionError",
    "DBConnectionExtension",
    "DBConnectionExtensionBuilder",
    "DBConnectionRuntime",
    "DBConnectionSettings",
    "DBConnectionSettingsPatch",
    "DefaultAPIMapper",
    "DefaultSQLModelConnectionRepository",
    "DefaultSQLModelConnectionUnitOfWork",
    "DefaultSQLModelConnectionUnitOfWorkFactory",
    "DefaultStoredConnection",
    "DriverOptionsBase",
    "DriverSpec",
    "EncryptionProvider",
    "ErrorMapper",
    "ErrorResponseSpec",
    "FernetEncryptionProvider",
    "InfrastructureError",
    "KindSpec",
    "NoDriverOptions",
    "NoOpConnectionOwnershipResolver",
    "NoOpEncryptionProvider",
    "ODBCDriverOptions",
    "SecretDecryptionError",
    "StoredConnectionIssue",
    "StoredConnectionRecordMapper",
    "TypeSpec",
    "ValidatedConnection",
    "ValidationFailedError",
    "apply_dsl_registry",
    "apply_dsl_settings",
    "build_connection_create_model",
    "build_connection_read_model",
    "build_connection_update_model",
    "build_default_registry",
    "load_dsl_data",
    "load_dsl_file",
    "load_registry_plugins",
]
