from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..connectors.base import Connector
from .drivers import DriverSpec, NoDriverOptions


@dataclass(slots=True)
class KindSpec:
    name: str
    description: str = ""
    capabilities: set[str] = field(default_factory=set)


@dataclass(slots=True)
class TypeSpec:
    name: str
    kind: str
    properties_model: type[BaseModel]
    secrets_model: type[BaseModel] | None = None
    public_model: type[BaseModel] | None = None
    connector_factory: Callable[[], Connector] | None = None
    default_driver: str | None = None
    driver_specs: list[DriverSpec] = field(default_factory=list)
    supported_drivers: set[str] = field(default_factory=set)
    capabilities: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.driver_specs:
            legacy_drivers = set(self.supported_drivers)
            if self.default_driver is not None:
                legacy_drivers.add(self.default_driver)
            self.driver_specs = [
                DriverSpec(name=driver_name, options_model=NoDriverOptions)
                for driver_name in sorted(legacy_drivers)
            ]

        self.supported_drivers = {driver_spec.name for driver_spec in self.driver_specs}
        if self.default_driver is not None and self.default_driver not in self.supported_drivers:
            raise ValueError(
                f"Default driver '{self.default_driver}' is not declared for type '{self.name}'."
            )
