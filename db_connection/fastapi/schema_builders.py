from __future__ import annotations

from types import NoneType
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from ..domain.drivers import DriverSpec, NoDriverOptions
from ..fastapi.schemas import (
    ConnectionCreateRequest,
    ConnectionReadResponse,
    ConnectionUpdateRequest,
)
from ..registry.base import ConnectionRegistry


def build_connection_kind_type(registry: ConnectionRegistry) -> type:
    return _build_open_string_literal(tuple(connection_kind.name for connection_kind in registry.list_kinds()))


def build_connection_type_type(registry: ConnectionRegistry) -> type:
    return _build_open_string_literal(tuple(connection_type.name for connection_type in registry.list_types()))


def build_connection_create_model(registry: ConnectionRegistry, base_model: type[BaseModel] | None = None) -> Any:
    return _build_union(_build_typed_create_models(registry, __base__=base_model or ConnectionCreateRequest), ConnectionCreateRequest)


def build_connection_update_model(registry: ConnectionRegistry, base_model: type[BaseModel] | None = None) -> Any:
    return _build_union(_build_typed_update_models(registry, __base__=base_model or ConnectionUpdateRequest), ConnectionUpdateRequest)


def build_connection_read_model(registry: ConnectionRegistry, base_model: type[BaseModel] | None = None) -> Any:
    return _build_union(_build_typed_read_models(registry, __base__=base_model or ConnectionReadResponse), ConnectionReadResponse)


def _build_typed_create_models(registry: ConnectionRegistry, __base__: type[BaseModel] | None = None) -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for connection_type in registry.list_types():
        for variant in _build_driver_variants(connection_type):
            models.append(
                create_model(
                    _build_model_name(
                        connection_type.kind,
                        connection_type.name,
                        "ConnectionCreateRequest",
                        variant["suffix"],
                    ),
                    __base__=__base__ or ConnectionCreateRequest,
                    kind=(Literal[connection_type.kind], ...),
                    type=(Literal[connection_type.name], ...),
                    driver=variant["driver_field"],
                    driver_options=variant["driver_options_field"],
                    properties=(connection_type.properties_model, ...),
                    secrets=(
                        _resolve_secrets_annotation(connection_type.secrets_model),
                        Field(default_factory=dict),
                    ),
                )
            )
    return models


def _build_typed_update_models(registry: ConnectionRegistry, __base__: type[BaseModel] | None = None) -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for connection_type in registry.list_types():
        for variant in _build_driver_variants(connection_type):
            driver_options_annotation, _ = variant["driver_options_field"]
            models.append(
                create_model(
                    _build_model_name(
                        connection_type.kind,
                        connection_type.name,
                        "ConnectionUpdateRequest",
                        variant["suffix"],
                    ),
                    __base__=__base__ or ConnectionUpdateRequest,
                    driver=variant["driver_field"],
                    driver_options=(driver_options_annotation | None, None)
                    if driver_options_annotation is not NoneType
                    else (NoneType, None),
                    properties=(connection_type.properties_model | None, None),
                    secrets=(
                        _resolve_secrets_annotation(connection_type.secrets_model) | None,
                        None,
                    ),
                )
            )
    return models


def _build_typed_read_models(registry: ConnectionRegistry, __base__: type[BaseModel] | None = None) -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for connection_type in registry.list_types():
        public_model = connection_type.public_model or connection_type.properties_model
        for variant in _build_driver_variants(connection_type, public=True):
            models.append(
                create_model(
                    _build_model_name(
                        connection_type.kind,
                        connection_type.name,
                        "ConnectionReadResponse",
                        variant["suffix"],
                    ),
                    __base__=__base__ or ConnectionReadResponse,
                    kind=(Literal[connection_type.kind], ...),
                    type=(Literal[connection_type.name], ...),
                    driver=variant["driver_field"],
                    driver_options=variant["driver_options_field"],
                    properties=(public_model, ...),
                )
            )
    return models


def _build_driver_variants(connection_type, *, public: bool = False) -> list[dict[str, Any]]:
    if not connection_type.driver_specs:
        no_driver_variant = {
            "suffix": "NoDriver",
            "driver_field": (NoneType, None),
            "driver_options_field": (NoneType, None),
        }
        return [no_driver_variant]

    variants: list[dict[str, Any]] = []
    for driver_spec in connection_type.driver_specs:
        is_default_driver = driver_spec.name == connection_type.default_driver
        driver_annotation = (
            Literal[driver_spec.name] | None
            if is_default_driver
            else Literal[driver_spec.name]
        )
        driver_default = None if is_default_driver else ...
        variant = {
            "suffix": _build_driver_suffix(driver_spec, is_default_driver),
            "driver_field": (driver_annotation, driver_default),
            "driver_options_field": _build_driver_options_field(
                driver_spec,
                required=is_default_driver or driver_spec.options_model is not NoDriverOptions,
                public=public,
            ),
        }
        variants.append(
            variant
        )
    return variants


def _build_driver_options_field(driver_spec: DriverSpec, *, required: bool, public: bool) -> tuple[Any, Any]:
    model = driver_spec.public_options_model if public else driver_spec.options_model
    if model is None or model is NoDriverOptions:
        return (NoDriverOptions | None, None)
    if required:
        return (model, ...)
    return (model | None, None)


def _build_union(models: list[Any], fallback: Any) -> Any:
    if not models:
        return fallback
    if len(models) == 1:
        return models[0]

    union_model = models[0]
    for model in models[1:]:
        union_model = union_model | model
    return union_model


def _build_open_string_literal(values: tuple[str, ...]) -> type:
    if not values:
        return str
    return Literal[values] | str


def _build_model_name(kind: str, connection_type: str, suffix: str, variant_suffix: str) -> str:
    return f"{connection_type.capitalize()}{kind.capitalize()}{variant_suffix}{suffix}"


def _build_driver_suffix(driver_spec: DriverSpec, is_default_driver: bool) -> str:
    normalized_name = driver_spec.name.replace("-", "_").replace("+", "_").title().replace("_", "")
    return f"{normalized_name}DefaultDriver" if is_default_driver else normalized_name


def _resolve_secrets_annotation(secrets_model: type[BaseModel] | None) -> Any:
    if secrets_model is None:
        return dict[str, Any]
    return secrets_model
