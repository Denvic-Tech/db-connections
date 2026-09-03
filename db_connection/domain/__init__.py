# pylint: disable=duplicate-code

from .drivers import DriverOptionsBase, DriverSpec, NoDriverOptions, ODBCDriverOptions
from .entities.check_result import ConnectionCheckResult
from .entities.draft import ConnectionDraft, build_draft_fields, extract_draft_extra
from .entities.list_query import ConnectionListQuery
from .entities.patch import (
    ConnectionPatch,
    build_connection_patch_fields,
    is_patch_unset,
    patch_fields_set,
    patch_to_dict,
)
from .entities.record import ConnectionRecord, StoredConnectionIssue
from .entities.validated import ValidatedConnection
from .repositories import ConnectionRepository
from .specs import KindSpec, TypeSpec

__all__ = [
    "ConnectionCheckResult",
    "ConnectionDraft",
    "ConnectionListQuery",
    "ConnectionPatch",
    "ConnectionRecord",
    "ConnectionRepository",
    "DriverOptionsBase",
    "DriverSpec",
    "KindSpec",
    "NoDriverOptions",
    "ODBCDriverOptions",
    "StoredConnectionIssue",
    "TypeSpec",
    "ValidatedConnection",
    "build_connection_patch_fields",
    "build_draft_fields",
    "extract_draft_extra",
    "is_patch_unset",
    "patch_fields_set",
    "patch_to_dict",
]
