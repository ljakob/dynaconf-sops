"""Parsing of ``@sops`` references (pure functions, no I/O)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ._errors import SopsError

__all__ = ["Reference", "build_expression", "parse_reference"]

_NAME_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+):(?P<path>.*)$", re.DOTALL)
_FORBIDDEN_IN_SEGMENT = frozenset('[]"')
SOPS_SUFFIX = ".sops.yaml"


@dataclass(frozen=True)
class Reference:
    """A parsed reference.

    Attributes:
        text: The reference as written (after the ``@sops`` token, stripped).
        file: Absolute path of the SOPS file.
        path: The key path as written (dotted keys or a ``[...]`` expression).
        expr: The sops ``--extract`` expression, or ``None`` for the whole document.
        sops_dir: The SOPS directory the file was resolved against, or ``None``
            (absolute path, or relative to the current directory).
        sops_dir_source: Where ``sops_dir`` came from (for error messages).
    """

    text: str
    file: Path
    path: str
    expr: str | None
    sops_dir: Path | None = None
    sops_dir_source: str | None = None


def _error(text: str, reason: str, *, path: str | None = None) -> SopsError:
    return SopsError(f"invalid @sops reference {text!r}: {reason}", reference=text, path=path)


def build_expression(text: str, path: str) -> str | None:
    """Translate a key path into a sops ``--extract`` expression.

    ``""`` gives ``None`` (whole document), ``a.b.0`` gives ``["a"]["b"][0]`` and
    a path starting with ``[`` is returned verbatim.
    """
    if path == "":
        return None
    if path.startswith("["):
        if not path.endswith("]"):
            raise _error(text, "a '[...]' path must end with ']'", path=path)
        return path
    parts: list[str] = []
    for segment in path.split("."):
        if segment == "":
            raise _error(
                text, "empty key in path (check for '..' or a leading/trailing '.')", path=path
            )
        if _FORBIDDEN_IN_SEGMENT & set(segment):
            raise _error(
                text,
                "keys containing '[', ']' or '\"' need the '[...]' form, "
                'e.g. #["my.key"]["sub"]',
                path=path,
            )
        if segment.isdigit() and segment.isascii():
            parts.append(f"[{int(segment)}]")
        else:
            parts.append(f'["{segment}"]')
    return "".join(parts)


def parse_reference(
    text: str, sops_dir: Path | str | None = None, sops_dir_source: str = "DYNACONF_SOPS_DIR"
) -> Reference:
    """Parse a reference into file, path and extract expression.

    Two forms are accepted:

    * ``<file>#<path>``: ``file`` is absolute, ``~``-expanded, or relative to
      ``sops_dir`` (or the current directory if ``sops_dir`` is ``None``).
    * ``<name>:<path>``: shorthand for ``<sops_dir>/<name>.sops.yaml``; needs
      a ``sops_dir``.

    ``sops_dir_source`` names where ``sops_dir`` comes from, for messages.

    Raises:
        SopsError: if the reference is malformed, or a shorthand is used
            without a ``sops_dir``. The message contains the reference, never
            a value.
    """
    text = text.strip()
    if not text:
        raise _error(text, "empty reference, expected '<file>#<path>' or '<name>:<path>'")

    if "#" in text:
        file_part, _, path = text.partition("#")
        file_part = file_part.strip()
        if not file_part:
            raise _error(text, "missing file before '#'")
    else:
        match = _NAME_RE.match(text)
        if match is None:
            raise _error(
                text,
                "expected '<file>#<path>' or '<name>:<path>' "
                "(name may contain only letters, digits, '_', '.', '-')",
            )
        file_part = match["name"] + SOPS_SUFFIX
        path = match["path"]
        if not sops_dir:
            explicit = f"{file_part}#{path.strip()}"
            raise SopsError(
                f"@sops {text}: the shorthand 'name:path' needs a sops dir, but "
                f"{sops_dir_source} is not set (set it, call "
                f"dynaconf_sops.register(sops_dir=...), or write an explicit path "
                f"{explicit!r})",
                reference=text,
                path=path.strip(),
            )

    path = path.strip()
    expr = build_expression(text, path)

    file = Path(os.path.expanduser(file_part))
    base: Path | None = None
    if not file.is_absolute():
        if sops_dir:
            base = Path(os.path.abspath(os.path.expanduser(str(sops_dir))))
            file = base / file
        else:
            file = Path.cwd() / file
    return Reference(
        text=text,
        file=Path(os.path.abspath(file)),
        path=path,
        expr=expr,
        sops_dir=base,
        sops_dir_source=sops_dir_source if base is not None else None,
    )
