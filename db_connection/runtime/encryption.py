from __future__ import annotations

import json
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

from ..errors import SecretDecryptionError


class EncryptionProvider(Protocol):
    def encrypt(self, payload: dict[str, Any]) -> str:
        ...

    def decrypt(self, payload: str | None) -> dict[str, Any]:
        ...


class NoOpEncryptionProvider:
    def encrypt(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload)

    def decrypt(self, payload: str | None) -> dict[str, Any]:
        if payload is None or payload == "":
            return {}
        return json.loads(payload)


class FernetEncryptionProvider:
    def __init__(self, key: str | bytes | Fernet) -> None:
        if isinstance(key, Fernet):
            self._fernet = key
        else:
            key_bytes = key.encode("utf-8") if isinstance(key, str) else key
            self._fernet = Fernet(key_bytes)

    def encrypt(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload).encode("utf-8")
        return self._fernet.encrypt(raw).decode("utf-8")

    def decrypt(self, payload: str | None) -> dict[str, Any]:
        if payload is None or payload == "":
            return {}
        try:
            raw = self._fernet.decrypt(payload.encode("utf-8"))
        except InvalidToken as exc:
            raise SecretDecryptionError("Could not decrypt connection secrets.") from exc
        return json.loads(raw.decode("utf-8"))
