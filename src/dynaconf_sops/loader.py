"""Zero-code activation: a Dynaconf loader that turns ``"@sops ..."`` strings lazy.

Add this module to ``LOADERS_FOR_DYNACONF`` (in the settings file or as an
environment variable) and keep Dynaconf's env loader in the list::

    LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]

Dynaconf runs loaders after the settings files and the env loader. ``load()``
registers the ``@sops`` converter and replaces every remaining ``"@sops ..."``
string (from files or environment variables, including combined forms such as
``"@sops @format ..."``) by a lazy value. Nothing is decrypted while loading;
sops runs on first access of each value.
"""

from __future__ import annotations

from typing import Any

from dynaconf.loaders.base import SourceMetadata
from dynaconf.utils.parse_conf import parse_conf_data

from ._converter import register
from ._walk import is_reference_string, iter_items

__all__ = ["load"]

IDENTIFIER = "dynaconf_sops"


def load(
    obj: Any,
    env: str | None = None,
    silent: bool = True,
    key: str | None = None,
    filename: str | None = None,
    validate: bool = False,
) -> None:
    """Dynaconf loader entry point (signature required by Dynaconf).

    Nested values are replaced in place with plain ``dict``/``list`` methods and
    top-level values with ``obj.set()``. Neither evaluates other lazy values in
    the same section, so loading never runs sops.
    """
    register()
    store = obj.store
    top_level: list[tuple[Any, str]] = []
    for item in iter_items(store):
        if not is_reference_string(item.value):
            continue
        if item.container is store:
            top_level.append((item.key, item.value))
            continue
        lazy = parse_conf_data(item.value, tomlfy=False, box_settings=obj)
        if isinstance(item.container, dict):
            dict.__setitem__(item.container, item.key, lazy)
        else:
            list.__setitem__(item.container, item.key, lazy)

    source = SourceMetadata(
        loader=IDENTIFIER, identifier="loader", env=(env or "global").lower(), merged=False
    )
    for name, value in top_level:
        lazy = parse_conf_data(value, tomlfy=False, box_settings=obj)
        obj.set(name, lazy, loader_identifier=source, validate=False)
