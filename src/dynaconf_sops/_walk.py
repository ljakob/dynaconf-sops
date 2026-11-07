"""Walk Dynaconf's store without evaluating lazy values.

Dynaconf's containers (``DataDict``/``DataList`` in 3.3, ``DynaBox``/``BoxList``
in 3.2) are ``dict``/``list`` subclasses whose ``__getitem__``/``get`` evaluate
lazy values. The plain ``dict``/``list`` methods used here never do.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from dynaconf.utils.parse_conf import Lazy

from ._converter import TOKEN, _convert

__all__ = ["Item", "describe", "is_reference_lazy", "is_reference_string", "iter_items"]


@dataclass(frozen=True)
class Item:
    """One value in the store with its location."""

    path: str
    container: dict[Any, Any] | list[Any]
    key: Any
    value: Any


def _join(prefix: str, key: Any, is_index: bool) -> str:
    if is_index:
        return f"{prefix}[{key}]"
    return f"{prefix}.{key}" if prefix else str(key)


def iter_items(container: Any, prefix: str = "") -> Iterator[Item]:
    """Yield every leaf (non-container) value, depth first, without evaluating."""
    if isinstance(container, dict):
        pairs: list[tuple[Any, Any]] = list(dict.items(container))
        is_index = False
    elif isinstance(container, list):
        pairs = list(enumerate(list.__iter__(container)))
        is_index = True
    else:  # pragma: no cover - callers pass containers only
        return
    for key, value in pairs:
        path = _join(prefix, key, is_index)
        if isinstance(value, (dict, list)):
            yield from iter_items(value, path)
        else:
            yield Item(path=path, container=container, key=key, value=value)


def is_reference_string(value: Any) -> bool:
    """``True`` for an unconverted ``"@sops ..."`` string."""
    return isinstance(value, str) and (value == TOKEN or value.startswith(TOKEN + " "))


def is_reference_lazy(value: Any) -> bool:
    """``True`` for a Lazy value created by the ``@sops`` converter."""
    return isinstance(value, Lazy) and getattr(value, "casting", None) is _convert


def describe(value: Any) -> str:
    """The reference as written in the settings, e.g. ``@sops @format {env[X]}/a#b``."""
    if isinstance(value, str):
        return value
    token = getattr(value.formatter, "token", TOKEN)
    if token == TOKEN:
        return f"{TOKEN} {value.value}"
    return f"{TOKEN} @{token} {value.value}"
