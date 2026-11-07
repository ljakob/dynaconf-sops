"""Lazy ``@sops`` token for Dynaconf.

Reference values in SOPS-encrypted files directly from your settings.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dynaconf-sops")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
