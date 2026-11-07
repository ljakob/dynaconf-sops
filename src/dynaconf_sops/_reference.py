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
    """

    text: str
    file: Path
    path: str
    expr: str | None


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


def parse_reference(text: str, sops_dir: Path | str | None = None) -> Reference:
    """Parse a reference into file, path and extract expression.

    Two forms are accepted:

    * ``<file>#<path>``: ``file`` is absolute, ``~``-expanded, or relative to
      ``sops_dir`` (or the current directory if ``sops_dir`` is ``None``).
    * ``<name>:<path>``: shorthand for ``<sops_dir>/<name>.sops.yaml``.

    Raises:
        SopsError: if the reference is malformed. The message contains the
            reference, never a value.
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

    path = path.strip()
    expr = build_expression(text, path)

    file = Path(os.path.expanduser(file_part))
    if not file.is_absolute():
        base = Path(os.path.expanduser(str(sops_dir))) if sops_dir else Path.cwd()
        file = base / file
    return Reference(text=text, file=Path(os.path.abspath(file)), path=path, expr=expr)
