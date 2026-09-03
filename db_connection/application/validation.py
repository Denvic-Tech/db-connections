from __future__ import annotations

from pydantic import ValidationError

from ..domain.drivers import DriverOptionsBase
from ..domain.entities import ConnectionDraft, ConnectionRecord, ValidatedConnection
from ..errors import ValidationFailedError
from ..registry.base import ConnectionRegistry
from ._driver_options import validate_driver_options


class ValidationService:
    def __init__(self, registry: ConnectionRegistry) -> None:
        self._registry = registry

    def validate(self, draft: ConnectionDraft | ConnectionRecord) -> ValidatedConnection:
        spec = self._registry.get_type(draft.type)
        if draft.kind != spec.kind:
            raise ValidationFailedError(f"Type '{draft.type}' belongs to kind '{spec.kind}', received '{draft.kind}'.")

        effective_driver = draft.driver or spec.default_driver
        if effective_driver and spec.supported_drivers and effective_driver not in spec.supported_drivers:
            raise ValidationFailedError(f"Driver '{effective_driver}' is not supported for type '{draft.type}'.")

        try:
            properties = spec.properties_model.model_validate(draft.properties)
            secrets = None if spec.secrets_model is None else spec.secrets_model.model_validate(draft.secrets)
        except ValidationError as exc:
            error_details = {"errors": exc.errors()}
            raise ValidationFailedError(
                "Connection payload validation failed.",
                details=error_details,
            ) from exc

        driver_options = self._validate_driver_options(
            spec=spec,
            connection_type=draft.type,
            effective_driver=effective_driver,
            raw_options=draft.driver_options,
        )
        return ValidatedConnection(
            name=draft.name,
            kind=draft.kind,
            type=draft.type,
            driver=effective_driver,
            driver_options=driver_options,
            properties=properties,
            secrets=secrets,
            labels=dict(draft.labels),
            metadata=dict(draft.metadata),
            extra=dict(draft.extra),
        )

    def _validate_driver_options(
        self,
        *,
        spec,
        connection_type: str,
        effective_driver: str | None,
        raw_options: dict[str, object] | DriverOptionsBase | None,
    ) -> DriverOptionsBase | None:
        return validate_driver_options(
            spec=spec,
            connection_type=connection_type,
            effective_driver=effective_driver,
            raw_options=raw_options,
        )
