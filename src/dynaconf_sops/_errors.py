"""Exception type raised by dynaconf-sops."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

__all__ = ["SopsError"]


class SopsError(ValueError):
    """A ``@sops`` reference could not be parsed or decrypted.

    The message contains the reference, the file, the sops return code and at
    most the first line of sops' stderr. It never contains a secret value.

    Attributes:
        reference: The reference text after the ``@sops`` token.
        file: The absolute SOPS file, if it could be determined.
        path: The key path as written in the reference, if any.
        returncode: The sops exit code, if sops ran.
        errors: For an aggregated error (``verify()``), the individual errors.
    """

    def __init__(
        self,
        message: str,
        *,
        reference: str | None = None,
        file: Path | None = None,
        path: str | None = None,
        returncode: int | None = None,
        errors: Sequence[SopsError] = (),
    ) -> None:
        super().__init__(message)
        self.reference = reference
        self.file = file
        self.path = path
        self.returncode = returncode
        self.errors: tuple[SopsError, ...] = tuple(errors)
