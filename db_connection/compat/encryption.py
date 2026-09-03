from __future__ import annotations

from copy import deepcopy
from typing import Any

from cryptography.fernet import Fernet

from db_connection.runtime.encryption import FernetEncryptionProvider

FERNET_PREFIX = "fernet$"
SENSITIVE_FIELDS = {
    "password",
    "sasl_plain_password",
    "access_token_id",
    "access_token_key",
    "session_token",
}


def _get_fernet() -> Fernet | None:
    from db_connection.compat import extension_config as ext_config

    return getattr(ext_config, "fernet", None)


def _get_fernet_provider() -> FernetEncryptionProvider | None:
    fernet = _get_fernet()
    if fernet is None:
        return None
    return FernetEncryptionProvider(fernet)


def _encrypt_value(value: Any, fernet: Fernet) -> Any:
    if not isinstance(value, str) or value == "":
        return value
    if value.startswith(FERNET_PREFIX):
        return value
    token = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{FERNET_PREFIX}{token}"


def _decrypt_value(value: Any, fernet: Fernet) -> Any:
    if not isinstance(value, str):
        return value
    if not value.startswith(FERNET_PREFIX):
        return value
    token = value[len(FERNET_PREFIX):].encode("utf-8")
    try:
        return fernet.decrypt(token).decode("utf-8")
    except Exception:
        # Не удалось расшифровать (возможно, ключ сменился) — возвращаем исходное значение
        return value


def encrypt_sensitive_fields(payload: dict[str, Any]) -> dict[str, Any]:
    provider = _get_fernet_provider()
    if provider is None:
        return payload

    result = deepcopy(payload)
    for field in SENSITIVE_FIELDS:
        if field in result and result[field] is not None:
            result[field] = _encrypt_value(result[field], provider._fernet)
    return result


def decrypt_sensitive_fields(payload: dict[str, Any]) -> dict[str, Any]:
    provider = _get_fernet_provider()
    if provider is None:
        return payload

    result = deepcopy(payload)
    for field in SENSITIVE_FIELDS:
        if field in result and result[field] is not None:
            result[field] = _decrypt_value(result[field], provider._fernet)
    return result
