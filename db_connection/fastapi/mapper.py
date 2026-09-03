from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, TypeAdapter

from ..application.public_projection import BrokenPublicConnectionView, PublicConnectionView
from ..domain.entities import ConnectionDraft, ConnectionPatch, build_connection_patch_fields, extract_draft_extra
from .schemas import ConnectionCreateRequest, ConnectionUpdateRequest


@dataclass(slots=True)
class APISchemaSet:
    create: Any
    read: Any
    update: Any
    broken_read: Any | None = None
    connection_kind: Any | None = None
    connection_type: Any | None = None


class APIMapper(Protocol):
    def to_create_draft(self, payload: BaseModel) -> ConnectionDraft: ...

    def to_patch(self, payload: BaseModel) -> ConnectionPatch: ...

    def to_response(self, schema: Any, public_view: PublicConnectionView) -> Any: ...

    def to_broken_response(self, schema: Any, public_view: BrokenPublicConnectionView) -> Any: ...


class DefaultAPIMapper:
    def to_create_draft(self, payload: ConnectionCreateRequest) -> ConnectionDraft:
        raw = payload.model_dump(mode="python")
        extra = extract_draft_extra(raw)
        return ConnectionDraft(
            name=raw["name"],
            kind=raw["kind"],
            type=raw["type"],
            driver=raw.get("driver"),
            driver_options=raw.get("driver_options"),
            properties=raw.get("properties", {}),
            secrets=raw.get("secrets", {}),
            labels=raw.get("labels", {}),
            metadata=raw.get("metadata", {}),
            extra=extra,
        )

    def to_patch(self, payload: ConnectionUpdateRequest) -> ConnectionPatch:
        raw = payload.model_dump(exclude_unset=True, mode="python")
        extra = extract_draft_extra(raw)
        patch_data: dict[str, Any] = {}
        for field_name in build_connection_patch_fields():
            if field_name in raw:
                patch_data[field_name] = raw[field_name]
        if extra:
            patch_data["extra"] = extra

        return ConnectionPatch(**patch_data)

    def to_response(self, schema: type[BaseModel], public_view: PublicConnectionView) -> Any:
        data = {
            "id": public_view.id,
            "name": public_view.name,
            "kind": public_view.kind,
            "type": public_view.type,
            "driver": public_view.driver,
            "driver_options": (
                None if public_view.driver_options is None else public_view.driver_options.model_dump(mode="python")
            ),
            "properties": public_view.properties.model_dump(mode="python"),
            "labels": dict(public_view.labels),
            "metadata": dict(public_view.metadata),
            "created_at": public_view.created_at,
            "updated_at": public_view.updated_at,
            "deleted_at": public_view.deleted_at,
        }
        data.update(public_view.extra)
        return TypeAdapter(schema).validate_python(data)

    def to_broken_response(self, schema: type[BaseModel], public_view: BrokenPublicConnectionView) -> Any:
        data = {
            "state": public_view.state,
            "id": public_view.id,
            "name": public_view.name,
            "kind": public_view.kind,
            "type": public_view.type,
            "driver": public_view.driver,
            "labels": dict(public_view.labels),
            "metadata": dict(public_view.metadata),
            "created_at": public_view.created_at,
            "updated_at": public_view.updated_at,
            "deleted_at": public_view.deleted_at,
            "issues": [
                {
                    "field": issue.field,
                    "code": issue.code,
                    "message": issue.message,
                    "details": dict(issue.details),
                }
                for issue in public_view.issues
            ],
            "raw_properties": public_view.raw_properties,
            "raw_driver_options": public_view.raw_driver_options,
            "raw_secrets": public_view.raw_secrets,
        }
        data.update(public_view.extra)
        return TypeAdapter(schema).validate_python(data)
