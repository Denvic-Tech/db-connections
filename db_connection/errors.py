from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DBConnectionError(Exception):
    code = "db_connection_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConnectionNotFoundError(DBConnectionError):
    code = "connection_not_found"

    def __init__(self, connection_id: str) -> None:
        super().__init__("Connection not found.", details={"connection_id": connection_id})


class ConnectionTypeNotSupportedError(DBConnectionError):
    code = "connection_type_not_supported"

    def __init__(self, connection_type: str) -> None:
        super().__init__(
            "Connection type is not supported.",
            details={"type": connection_type},
        )


class ValidationFailedError(DBConnectionError):
    code = "validation_failed"


class AccessDeniedError(DBConnectionError):
    code = "access_denied"


class ConnectionLimitExceededError(DBConnectionError):
    code = "connection_limit_exceeded"

    def __init__(self, limit: int) -> None:
        super().__init__(
            "Connection limit exceeded.",
            details={"limit": limit},
        )


class SecretDecryptionError(DBConnectionError):
    code = "secret_decryption_failed"


class InfrastructureError(DBConnectionError):
    code = "infrastructure_error"


@dataclass(slots=True)
class ErrorResponseSpec:
    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


class ErrorMapper:
    def map_exception(self, exc: Exception) -> ErrorResponseSpec:
        if isinstance(exc, AccessDeniedError):
            status_code = 403
        elif isinstance(exc, ConnectionNotFoundError):
            status_code = 404
        elif isinstance(exc, ConnectionTypeNotSupportedError):
            status_code = 400
        elif isinstance(exc, ValidationFailedError):
            status_code = 422
        elif isinstance(exc, ConnectionLimitExceededError):
            status_code = 409
        elif isinstance(exc, DBConnectionError):
            status_code = 400
        else:
            return ErrorResponseSpec(
                500,
                "internal_error",
                "Internal server error.",
            )

        return ErrorResponseSpec(status_code, exc.code, exc.message, exc.details)
