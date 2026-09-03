from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, fields
from functools import lru_cache
from typing import Any, Final, TypeAlias, TypeVar

from ..drivers import DriverOptionsBase


class _PatchUnset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "PATCH_UNSET"


PATCH_UNSET: Final = _PatchUnset()
PatchUnset: TypeAlias = _PatchUnset
T = TypeVar("T")
PatchValue: TypeAlias = T | PatchUnset


@dataclass(slots=True, kw_only=True)
class ConnectionPatch:
    name: PatchValue[str | None] = PATCH_UNSET
    driver: PatchValue[str | None] = PATCH_UNSET
    driver_options: PatchValue[dict[str, Any] | DriverOptionsBase | None] = PATCH_UNSET
    properties: PatchValue[dict[str, Any] | None] = PATCH_UNSET
    secrets: PatchValue[dict[str, Any] | None] = PATCH_UNSET
    labels: PatchValue[dict[str, str] | None] = PATCH_UNSET
    metadata: PatchValue[dict[str, Any] | None] = PATCH_UNSET
    extra: PatchValue[dict[str, Any] | None] = PATCH_UNSET


def is_patch_unset(value: object) -> bool:
    return value is PATCH_UNSET


def patch_fields_set(patch: ConnectionPatch) -> frozenset[str]:
    return frozenset(
        field.name
        for field in fields(patch)
        if getattr(patch, field.name) is not PATCH_UNSET
    )


def patch_to_dict(patch: ConnectionPatch) -> dict[str, Any]:
    return {
        field.name: getattr(patch, field.name)
        for field in fields(patch)
        if getattr(patch, field.name) is not PATCH_UNSET
    }


@lru_cache
def build_connection_patch_fields() -> Collection[str]:
    return {field.name for field in fields(ConnectionPatch)}
