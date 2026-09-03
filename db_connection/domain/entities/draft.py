from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, fields
from functools import lru_cache
from typing import Any

from .envelope import ConnectionEnvelope


@dataclass(slots=True)
class ConnectionDraft(ConnectionEnvelope):
    pass


@lru_cache
def build_draft_fields() -> Collection[str]:
    return {field.name for field in fields(ConnectionDraft)}


def extract_draft_extra(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if key not in build_draft_fields()}
