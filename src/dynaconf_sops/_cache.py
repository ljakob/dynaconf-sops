"""Per-process cache of decrypted values (D-9).

The key is ``(absolute file, extract expression, mtime_ns, size)``, so a file
that changes on disk (rotation, ``git pull``) is decrypted again on the next
access. Concurrent first accesses of the same reference run sops once.
"""

from __future__ import annotations

import copy
import os
import threading
from collections.abc import Callable
from typing import Any

from ._config import Config
from ._reference import Reference
from ._runner import decrypt

__all__ = ["clear_cache", "lookup", "secret_values"]

_CacheKey = tuple[str, "str | None", int, int]

_lock = threading.Lock()
_values: dict[_CacheKey, Any] = {}
_ref_locks: dict[tuple[str, str | None], threading.Lock] = {}
_secrets: set[str] = set()


def _collect_strings(value: Any, out: set[str]) -> None:
    if isinstance(value, str):
        if value:
            out.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_strings(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, out)


def lookup(ref: Reference, config: Config | Callable[[], Config]) -> Any:
    """Return the decrypted value, from the cache if the file is unchanged.

    ``config`` may be a callable; it is only called when sops has to run, so a
    cache hit does not need the sops binary.
    """

    def get_config() -> Config:
        return config if isinstance(config, Config) else config()

    try:
        st = os.stat(ref.file)
    except OSError:
        return decrypt(ref, get_config())  # raises a SopsError with a clear message
    ident = (str(ref.file), ref.expr)
    key: _CacheKey = (*ident, st.st_mtime_ns, st.st_size)

    with _lock:
        if key in _values:
            return copy.deepcopy(_values[key])
        ref_lock = _ref_locks.setdefault(ident, threading.Lock())

    with ref_lock:
        with _lock:
            if key in _values:
                return copy.deepcopy(_values[key])
        value = decrypt(ref, get_config())
        with _lock:
            for stale in [k for k in _values if k[:2] == ident]:
                del _values[stale]
            _values[key] = value
            _collect_strings(value, _secrets)
        return copy.deepcopy(value)


def clear_cache() -> None:
    """Forget all cached values and the set returned by ``secret_values()``."""
    with _lock:
        _values.clear()
        _ref_locks.clear()
        _secrets.clear()


def secret_values() -> frozenset[str]:
    """Non-empty strings decrypted so far (including strings inside maps and lists)."""
    with _lock:
        return frozenset(_secrets)
