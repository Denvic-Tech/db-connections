from __future__ import annotations

from pydantic import BaseModel, ValidationError

from ..domain.drivers import DriverOptionsBase, DriverSpec, NoDriverOptions
from ..domain.specs import TypeSpec
from ..errors import ValidationFailedError


def validate_driver_options(
    *,
    spec: TypeSpec,
    connection_type: str,
    effective_driver: str | None,
    raw_options: dict[str, object] | DriverOptionsBase | None,
) -> DriverOptionsBase | None:
    if effective_driver is None:
        if is_empty_driver_options(raw_options):
            return None
        raise ValidationFailedError(f"Driver options are not supported for type '{connection_type}'.")

    driver_spec = resolve_driver_spec(spec, effective_driver)
    if driver_spec is None:
        raise ValidationFailedError(f"Driver '{effective_driver}' is not supported for type '{connection_type}'.")

    if driver_spec.options_model is NoDriverOptions:
        if is_empty_driver_options(raw_options):
            return None
        raise ValidationFailedError(
            f"Driver '{effective_driver}' for type '{connection_type}' does not accept driver options."
        )

    try:
        return driver_spec.options_model.model_validate(raw_options)
    except ValidationError as exc:
        error_details = {
            "driver": effective_driver,
            "type": connection_type,
            "errors": exc.errors(),
        }
        raise ValidationFailedError(
            "Driver options validation failed.",
            details=error_details,
        ) from exc


def build_public_driver_options(
    *,
    spec: TypeSpec,
    connection_type: str,
    effective_driver: str | None,
    raw_options: dict[str, object] | DriverOptionsBase | None,
) -> BaseModel | None:
    validated_options = validate_driver_options(
        spec=spec,
        connection_type=connection_type,
        effective_driver=effective_driver,
        raw_options=raw_options,
    )
    if validated_options is None:
        return None

    driver_spec = resolve_driver_spec(spec, effective_driver)
    if driver_spec is None:
        return None

    public_model = driver_spec.public_options_model or driver_spec.options_model
    try:
        return public_model.model_validate(validated_options.model_dump(mode="python"))
    except ValidationError as exc:
        error_details = {
            "driver": effective_driver,
            "type": connection_type,
            "errors": exc.errors(),
        }
        raise ValidationFailedError(
            "Stored driver options payload is invalid.",
            details=error_details,
        ) from exc


def resolve_driver_spec(spec: TypeSpec, driver_name: str) -> DriverSpec | None:
    return next(
        (driver_spec for driver_spec in spec.driver_specs if driver_spec.name == driver_name),
        None,
    )


def is_empty_driver_options(raw_options: dict[str, object] | DriverOptionsBase | None) -> bool:
    if raw_options is None:
        return True
    if isinstance(raw_options, BaseModel):
        return not raw_options.model_dump(mode="python")
    return not raw_options
