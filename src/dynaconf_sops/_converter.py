"""The ``@sops`` converter and ``register()`` (D-5 A, D-7)."""

from __future__ import annotations

import os
import threading
from typing import Any

from dynaconf import add_converter

from ._cache import lookup
from ._config import Settings
from ._reference import parse_reference

__all__ = ["TOKEN", "register", "resolve"]

TOKEN = "@sops"  # noqa: S105 - the Dynaconf token, not a password

_lock = threading.Lock()
_settings = Settings()
_registered = False


def resolve(text: str) -> Any:
    """Resolve the reference text after the ``@sops`` token to its value."""
    settings = _settings
    ref = parse_reference(str(text), settings.resolve_dir(), settings.dir_source())
    return lookup(ref, settings.resolve)


def _convert(value: Any) -> Any:
    return resolve(value)


_convert.__name__ = "sops"


def register(
    *,
    sops_dir: str | os.PathLike[str] | None = None,
    sops_bin: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
) -> None:
    """Register the ``@sops`` converter with Dynaconf and set configuration.

    Importing ``dynaconf_sops`` already calls ``register()``; calling it again
    is harmless. Arguments that are given override the environment variables
    ``DYNACONF_SOPS_DIR``, ``DYNACONF_SOPS_BIN`` and ``DYNACONF_SOPS_TIMEOUT``;
    arguments left as ``None`` keep their previous value.

    The converter must be registered before Dynaconf parses the settings files,
    otherwise ``"@sops ..."`` stays a plain string (use the loader
    ``dynaconf_sops.loader`` to convert those afterwards).

    Args:
        sops_dir: Base directory for relative files and ``name:path`` references.
        sops_bin: Path or command name of the sops binary.
        timeout: Seconds to wait for one sops call.
    """
    global _registered
    with _lock:
        if sops_dir is not None:
            _settings.sops_dir = sops_dir
        if sops_bin is not None:
            _settings.sops_bin = sops_bin
        if timeout is not None:
            _settings.timeout = timeout
        if not _registered:
            add_converter("sops", _convert)
            _registered = True


def _reset_for_tests() -> None:
    """Forget explicit configuration (test helper, not public API)."""
    with _lock:
        _settings.sops_dir = None
        _settings.sops_bin = None
        _settings.timeout = None
