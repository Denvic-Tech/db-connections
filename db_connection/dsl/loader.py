from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..domain.drivers import DriverSpec, NoDriverOptions
from ..domain.specs import KindSpec, TypeSpec
from ..errors import ValidationFailedError
from ..plugins import DEFAULT_PLUGIN_GROUP
from ..registry.base import ConnectionRegistry
from ..runtime.settings import DBConnectionSettings


class DSLSettingsModel(BaseModel):
    max_connections: int | None = None


class DSLKindSpecModel(BaseModel):
    name: str
    description: str = ""
    capabilities: set[str] = Field(default_factory=set)


class DSLTypeSpecModel(BaseModel):
    name: str
    kind: str
    properties_model: str
    secrets_model: str | None = None
    public_model: str | None = None
    connector_factory: str | None = None
    default_driver: str | None = None
    driver_specs: list[DSLDriverSpecModel] = Field(default_factory=list)
    supported_drivers: set[str] = Field(default_factory=set)
    capabilities: set[str] = Field(default_factory=set)
    tags: set[str] = Field(default_factory=set)


class DSLDriverSpecModel(BaseModel):
    name: str
    options_model: str | None = None
    public_options_model: str | None = None
    tags: set[str] = Field(default_factory=set)


class DSLPluginConfig(BaseModel):
    name: str
    group: str = DEFAULT_PLUGIN_GROUP


class DSLRegistryModel(BaseModel):
    kinds: list[DSLKindSpecModel] = Field(default_factory=list)
    types: list[DSLTypeSpecModel] = Field(default_factory=list)


class DBConnectionDSLConfig(BaseModel):
    settings: DSLSettingsModel = Field(default_factory=DSLSettingsModel)
    registry: DSLRegistryModel = Field(default_factory=DSLRegistryModel)
    plugins: list[DSLPluginConfig] = Field(default_factory=list)


def load_dsl_data(data: object) -> DBConnectionDSLConfig:
    return DBConnectionDSLConfig.model_validate(data)


def load_dsl_file(path: str | Path) -> DBConnectionDSLConfig:
    file_path = Path(path)
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationFailedError(
            "DB Connection DSL file could not be read.",
            details={"path": str(file_path)},
        ) from exc

    suffix = file_path.suffix.lower()
    if suffix == ".json":
        import json

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValidationFailedError(
                "DB Connection DSL JSON is invalid.",
                details={"path": str(file_path)},
            ) from exc
        return load_dsl_data(data)

    if suffix in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(raw_text) or {}
        except yaml.YAMLError as exc:
            raise ValidationFailedError(
                "DB Connection DSL YAML is invalid.",
                details={"path": str(file_path)},
            ) from exc
        return load_dsl_data(data)

    raise ValidationFailedError(
        "DB Connection DSL file format is not supported.",
        details={"path": str(file_path), "suffix": suffix},
    )


def apply_dsl_settings(
    settings: DBConnectionSettings,
    config: DBConnectionDSLConfig,
) -> DBConnectionSettings:
    return settings.model_copy(update=config.settings.model_dump(exclude_none=True))


def apply_dsl_registry(registry: ConnectionRegistry, config: DBConnectionDSLConfig) -> ConnectionRegistry:
    for kind in config.registry.kinds:
        registry.register_kind(
            KindSpec(
                name=kind.name,
                description=kind.description,
                capabilities=set(kind.capabilities),
            )
        )

    for connection_type in config.registry.types:
        registry.register_type(
            TypeSpec(
                name=connection_type.name,
                kind=connection_type.kind,
                properties_model=_resolve_model_class(connection_type.properties_model),
                secrets_model=_resolve_optional_model_class(connection_type.secrets_model),
                public_model=_resolve_optional_model_class(connection_type.public_model),
                connector_factory=_resolve_optional_callable(connection_type.connector_factory),
                default_driver=connection_type.default_driver,
                driver_specs=_build_driver_specs(connection_type),
                supported_drivers=set(connection_type.supported_drivers),
                capabilities=set(connection_type.capabilities),
                tags=set(connection_type.tags),
            )
        )

    return registry


def _resolve_model_class(reference: str) -> type[BaseModel]:
    resolved = _resolve_reference(reference)
    if not isinstance(resolved, type) or not issubclass(resolved, BaseModel):
        raise ValidationFailedError(
            "DSL reference must resolve to a Pydantic model class.",
            details={"reference": reference},
        )
    return resolved


def _resolve_optional_model_class(reference: str | None) -> type[BaseModel] | None:
    if reference is None:
        return None
    return _resolve_model_class(reference)


def _resolve_optional_callable(reference: str | None) -> Any:
    if reference is None:
        return None

    resolved = _resolve_reference(reference)
    if not callable(resolved):
        raise ValidationFailedError(
            "DSL reference must resolve to a callable.",
            details={"reference": reference},
        )
    return resolved


def _resolve_reference(reference: str) -> Any:
    module_name, attribute_path = _split_reference(reference)
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise ValidationFailedError(
            "DSL reference module could not be imported.",
            details={"reference": reference},
        ) from exc

    current: Any = module
    try:
        for attribute in attribute_path.split("."):
            current = getattr(current, attribute)
    except AttributeError as exc:
        raise ValidationFailedError(
            "DSL reference attribute could not be resolved.",
            details={"reference": reference},
        ) from exc
    return current


def _build_driver_specs(connection_type: DSLTypeSpecModel) -> list[DriverSpec]:
    if connection_type.driver_specs:
        return [
            DriverSpec(
                name=driver_spec.name,
                options_model=(
                    NoDriverOptions
                    if driver_spec.options_model is None
                    else _resolve_model_class(driver_spec.options_model)
                ),
                public_options_model=_resolve_optional_model_class(driver_spec.public_options_model),
                tags=set(driver_spec.tags),
            )
            for driver_spec in connection_type.driver_specs
        ]

    legacy_drivers = set(connection_type.supported_drivers)
    if connection_type.default_driver is not None:
        legacy_drivers.add(connection_type.default_driver)
    return [
        DriverSpec(name=driver_name, options_model=NoDriverOptions)
        for driver_name in sorted(legacy_drivers)
    ]


def _split_reference(reference: str) -> tuple[str, str]:
    if ":" in reference:
        module_name, attribute_path = reference.split(":", maxsplit=1)
    else:
        module_name, _, attribute_path = reference.rpartition(".")

    if not module_name or not attribute_path:
        raise ValidationFailedError(
            "DSL reference must be formatted as 'module.path:attribute' or 'module.path.attribute'.",
            details={"reference": reference},
        )
    return module_name, attribute_path
