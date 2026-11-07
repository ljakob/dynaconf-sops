"""Library configuration (D-7): explicit arguments, then environment, then defaults."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ._errors import SopsError

__all__ = [
    "DEFAULT_TIMEOUT",
    "ENV_BIN",
    "ENV_DIR",
    "ENV_TIMEOUT",
    "FALLBACK_BINARIES",
    "Config",
    "Settings",
    "find_sops",
]

ENV_DIR = "DYNACONF_SOPS_DIR"
ENV_BIN = "DYNACONF_SOPS_BIN"
ENV_TIMEOUT = "DYNACONF_SOPS_TIMEOUT"
DEFAULT_TIMEOUT = 30.0
FALLBACK_BINARIES: tuple[str, ...] = (
    "~/.local/bin/sops",
    "/usr/local/bin/sops",
    "/usr/bin/sops",
)


@dataclass(frozen=True)
class Config:
    """Effective configuration used for one decryption."""

    sops_dir: Path | None
    sops_bin: str
    timeout: float


@dataclass
class Settings:
    """Explicit settings from ``register()``; ``None`` means "not set"."""

    sops_dir: str | os.PathLike[str] | None = None
    sops_bin: str | os.PathLike[str] | None = None
    timeout: float | None = None

    def resolve(self) -> Config:
        """Combine explicit settings, environment and defaults."""
        return Config(
            sops_dir=_resolve_dir(self.sops_dir),
            sops_bin=find_sops(self.sops_bin),
            timeout=_resolve_timeout(self.timeout),
        )

    def resolve_dir(self) -> Path | None:
        """Only the SOPS directory (needed to parse a reference)."""
        return _resolve_dir(self.sops_dir)

    def dir_source(self) -> str:
        """Where the SOPS directory comes from, for error messages."""
        return "register(sops_dir=...)" if self.sops_dir is not None else ENV_DIR


def _resolve_dir(explicit: str | os.PathLike[str] | None) -> Path | None:
    value = os.fspath(explicit) if explicit is not None else os.environ.get(ENV_DIR, "")
    if not value:
        return None
    return Path(os.path.expanduser(value))


def _resolve_timeout(explicit: float | None) -> float:
    if explicit is not None:
        timeout = float(explicit)
        source = "timeout argument"
    else:
        raw = os.environ.get(ENV_TIMEOUT, "").strip()
        if not raw:
            return DEFAULT_TIMEOUT
        source = ENV_TIMEOUT
        try:
            timeout = float(raw)
        except ValueError:
            raise SopsError(f"{source} must be a number of seconds, got {raw!r}") from None
    if not timeout > 0:
        raise SopsError(f"{source} must be greater than 0, got {timeout!r}")
    return timeout


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_sops(explicit: str | os.PathLike[str] | None = None) -> str:
    """Locate the sops binary.

    Order: explicit argument, ``DYNACONF_SOPS_BIN``, ``sops`` on ``PATH``, then
    ``~/.local/bin/sops``, ``/usr/local/bin/sops``, ``/usr/bin/sops``.
    An explicit value may be a path or a command name looked up on ``PATH``.
    """
    configured = os.fspath(explicit) if explicit is not None else os.environ.get(ENV_BIN, "")
    if configured:
        source = "sops_bin argument" if explicit is not None else ENV_BIN
        candidate = os.path.expanduser(configured)
        if os.sep in candidate:
            if _executable(candidate):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
        raise SopsError(f"sops binary {configured!r} from {source} not found or not executable")

    found = shutil.which("sops")
    if found:
        return found
    for fallback in FALLBACK_BINARIES:
        candidate = os.path.expanduser(fallback)
        if _executable(candidate):
            return candidate
    searched = ", ".join(("PATH", *FALLBACK_BINARIES))
    raise SopsError(f"sops binary not found (searched {searched}); set {ENV_BIN} to its path")
