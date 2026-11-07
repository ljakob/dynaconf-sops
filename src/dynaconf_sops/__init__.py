"""Lazy ``@sops`` token for Dynaconf.

Reference values in SOPS-encrypted files directly from your settings::

    database:
      password: "@sops mariadb:users.app.password"

Importing this package registers the ``@sops`` converter. Alternatively, add
``dynaconf_sops.loader`` to ``LOADERS_FOR_DYNACONF`` for zero-code activation.
"""

import importlib.metadata as _metadata

from ._cache import clear_cache, secret_values
from ._converter import register
from ._errors import SopsError
from ._helpers import references, verify

try:
    __version__: str = _metadata.version("dynaconf-sops")
except _metadata.PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"

register()

__all__ = [
    "SopsError",
    "__version__",
    "clear_cache",
    "references",
    "register",
    "secret_values",
    "verify",
]
