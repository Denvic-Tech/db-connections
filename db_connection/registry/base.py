from __future__ import annotations

from dataclasses import replace

from ..domain.specs import KindSpec, TypeSpec
from ..errors import ConnectionTypeNotSupportedError, ValidationFailedError


class ConnectionRegistry:
    def __init__(self) -> None:
        self._kinds: dict[str, KindSpec] = {}
        self._types: dict[str, TypeSpec] = {}

    def register_kind(self, spec: KindSpec, overwrite: bool = False) -> None:
        if spec.name in self._kinds and not overwrite:
            raise ValidationFailedError(f"Kind '{spec.name}' is already registered.")
        self._kinds[spec.name] = spec

    def register_type(self, spec: TypeSpec, overwrite: bool = False) -> None:
        if spec.kind not in self._kinds:
            raise ValidationFailedError(f"Unknown kind '{spec.kind}' for type '{spec.name}'.")
        if spec.name in self._types and not overwrite:
            raise ValidationFailedError(f"Type '{spec.name}' is already registered.")
        self._types[spec.name] = spec

    def get_kind(self, name: str) -> KindSpec:
        try:
            return self._kinds[name]
        except KeyError as exc:
            raise ValidationFailedError(f"Unknown kind '{name}'.") from exc

    def get_type(self, name: str) -> TypeSpec:
        try:
            return self._types[name]
        except KeyError as exc:
            raise ConnectionTypeNotSupportedError(name) from exc

    def list_kinds(self) -> list[KindSpec]:
        return sorted(self._kinds.values(), key=lambda spec: spec.name)

    def list_types(self, *, kind: str | None = None) -> list[TypeSpec]:
        items = self._types.values()
        if kind is not None:
            items = [spec for spec in items if spec.kind == kind]
        return sorted(items, key=lambda spec: spec.name)

    def copy(self) -> ConnectionRegistry:
        registry = ConnectionRegistry()
        for kind_spec in self.list_kinds():
            registry.register_kind(replace(kind_spec))
        for type_spec in self.list_types():
            registry.register_type(replace(type_spec))
        return registry
