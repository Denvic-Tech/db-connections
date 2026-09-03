from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from db_connection.errors import DBConnectionError, InfrastructureError
from db_connection.registry.base import ConnectionRegistry

DEFAULT_PLUGIN_GROUP = "db_connection.plugins"


def load_registry_plugins(
    registry: ConnectionRegistry,
    *,
    group: str = DEFAULT_PLUGIN_GROUP,
    names: Iterable[str] | None = None,
) -> list[str]:
    plugins = _select_entry_points(group=group, names=names)
    loaded: list[str] = []
    for plugin in plugins:
        bootstrap = _load_plugin_callable(plugin)
        try:
            bootstrap(registry)
        except DBConnectionError:
            raise
        except Exception as exc:
            raise InfrastructureError(
                "DB Connection plugin bootstrap failed.",
                details={"group": group, "plugin": plugin.name},
            ) from exc
        loaded.append(plugin.name)
    return loaded


def _select_entry_points(
    *,
    group: str,
    names: Iterable[str] | None,
) -> list[EntryPoint]:
    selected = _entry_points_for_group(group)
    if names is None:
        return selected

    requested_names = set(names)
    filtered = [plugin for plugin in selected if plugin.name in requested_names]
    found_names = {plugin.name for plugin in filtered}
    missing = sorted(requested_names - found_names)
    if missing:
        raise InfrastructureError(
            "DB Connection plugins were not found.",
            details={"group": group, "plugins": missing},
        )
    return filtered


def _entry_points_for_group(group: str) -> list[EntryPoint]:
    discovered = entry_points()
    selector = getattr(discovered, "select", None)
    items = selector(group=group) if selector is not None else _legacy_entry_points_for_group(discovered, group)
    return sorted(items, key=lambda plugin: plugin.name)


def _legacy_entry_points_for_group(discovered: Any, group: str) -> Any:
    return discovered.get(group, [])


def _load_plugin_callable(plugin: EntryPoint) -> Callable[[ConnectionRegistry], Any]:
    try:
        bootstrap = plugin.load()
    except Exception as exc:
        raise InfrastructureError(
            "DB Connection plugin could not be imported.",
            details={"group": plugin.group, "plugin": plugin.name},
        ) from exc

    if not callable(bootstrap):
        raise InfrastructureError(
            "DB Connection plugin must resolve to a callable bootstrap.",
            details={"group": plugin.group, "plugin": plugin.name},
        )
    return bootstrap
