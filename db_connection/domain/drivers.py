from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field


class DriverOptionsBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class NoDriverOptions(DriverOptionsBase):
    pass


class ODBCDriverOptions(DriverOptionsBase):
    odbc_driver_name: str = Field(validation_alias="driver_name")


@dataclass(slots=True)
class DriverSpec:
    name: str
    options_model: type[DriverOptionsBase] = NoDriverOptions
    public_options_model: type[BaseModel] | None = None
    tags: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.public_options_model is None:
            self.public_options_model = self.options_model
