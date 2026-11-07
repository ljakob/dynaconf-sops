"""Lazy ``@sops`` token for Dynaconf.

Reference values in SOPS-encrypted files directly from your settings::

    database:
      password: "@sops mariadb:users.app.password"

Importing this package registers the ``@sops`` converter. Alternatively, add
``dynaconf_sops.loader`` to ``LOADERS_FOR_DYNACONF`` for zero-code activation.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._cache import clear_cache, secret_values
from ._converter import register
from ._errors import SopsError

try:
    __version__ = version("dynaconf-sops")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"

register()

__all__ = [
    "SopsError",
    "__version__",
    "clear_cache",
    "register",
    "secret_values",
]
