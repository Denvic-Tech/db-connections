# pylint: disable=redefined-builtin

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..domain.entities import ConnectionRecord, StoredConnectionIssue
from ..infra.sa_types import DriverOptionsType
from ..runtime.encryption import EncryptionProvider, NoOpEncryptionProvider


class StoredConnectionRecordMapper:
    def __init__(
        self,
        *,
        encryption_provider: EncryptionProvider | None = None,
        driver_options_type: DriverOptionsType | None = None,
    ) -> None:
        self._encryption_provider = encryption_provider or NoOpEncryptionProvider()
        self._driver_options_type = driver_options_type or DriverOptionsType()

    def to_record(
        self,
        *,
        id: Any,
        name: Any,
        kind: Any,
        type: Any,
        created_at: Any,
        updated_at: Any,
        driver: Any = None,
        driver_options_json: Any = None,
        properties_json: Any,
        secrets_ciphertext: Any,
        labels_json: Any,
        metadata_json: Any,
        extra_json: Any = None,
        extra: Any = None,
        deleted_at: Any = None,
    ) -> ConnectionRecord:
        issues: list[StoredConnectionIssue] = []
        driver_options, raw_driver_options = self._decode_driver_options(driver_options_json, issues)
        properties, raw_properties = self._coerce_mapping(
            properties_json,
            field_name="properties",
            code="invalid_properties",
            message="Stored connection properties payload is invalid.",
            issues=issues,
        )
        secrets, raw_secrets = self._decode_secrets(secrets_ciphertext, issues)
        labels, _ = self._coerce_mapping(
            labels_json,
            field_name="labels",
            code="invalid_labels",
            message="Stored connection labels payload is invalid.",
            issues=issues,
            value_type=str,
        )
        metadata, _ = self._coerce_mapping(
            metadata_json,
            field_name="metadata",
            code="invalid_metadata",
            message="Stored connection metadata payload is invalid.",
            issues=issues,
        )
        extra_payload = extra if extra is not None else extra_json
        extra_data, _ = self._coerce_mapping(
            extra_payload,
            field_name="extra",
            code="invalid_extra",
            message="Stored connection extra payload is invalid.",
            issues=issues,
        )
        return ConnectionRecord(
            id=str(id),
            name=str(name),
            kind=str(kind),
            type=str(type),
            driver=driver,
            driver_options=driver_options,
            properties=properties,
            secrets=secrets,
            labels=labels,
            metadata=metadata,
            extra=extra_data,
            created_at=created_at,
            updated_at=updated_at,
            deleted_at=deleted_at,
            read_issues=issues,
            raw_properties=raw_properties,
            raw_driver_options=raw_driver_options,
            raw_secrets=raw_secrets,
        )

    def _decode_driver_options(
        self,
        raw_value: Any,
        issues: list[StoredConnectionIssue],
    ) -> tuple[BaseModel | None, Any | None]:
        if raw_value is None:
            return None, None
        try:
            return self._driver_options_type.process_result_value(raw_value, None), None
        except Exception as exc:
            issues.append(
                StoredConnectionIssue(
                    field="driver_options",
                    code="invalid_driver_options",
                    message="Stored connection driver options payload is invalid.",
                    details={"error": str(exc)},
                )
            )
            return None, raw_value

    def _decode_secrets(
        self,
        ciphertext: Any,
        issues: list[StoredConnectionIssue],
    ) -> tuple[dict[str, Any], Any | None]:
        try:
            decoded = self._encryption_provider.decrypt(ciphertext)
        except Exception as exc:
            issues.append(
                StoredConnectionIssue(
                    field="secrets",
                    code="unreadable_secrets",
                    message="Stored connection secrets could not be decrypted.",
                    details={"error": str(exc)},
                )
            )
            return {}, None

        if isinstance(decoded, dict):
            return dict(decoded), None

        issues.append(
            StoredConnectionIssue(
                field="secrets",
                code="invalid_secrets",
                message="Stored connection secrets payload is invalid.",
                details={"raw_type": type(decoded).__name__},
            )
        )
        return {}, decoded

    def _coerce_mapping(
        self,
        raw_value: Any,
        *,
        field_name: str,
        code: str,
        message: str,
        issues: list[StoredConnectionIssue],
        value_type: type | None = None,
    ) -> tuple[dict[str, Any], Any | None]:
        if isinstance(raw_value, dict):
            mapping = dict(raw_value)
            if value_type is not None and not all(isinstance(value, value_type) for value in mapping.values()):
                issues.append(
                    StoredConnectionIssue(
                        field=field_name,
                        code=code,
                        message=message,
                        details={"raw_type": type(raw_value).__name__},
                    )
                )
                return {}, raw_value
            return mapping, None

        issues.append(
            StoredConnectionIssue(
                field=field_name,
                code=code,
                message=message,
                details={"raw_type": type(raw_value).__name__},
            )
        )
        return {}, raw_value
