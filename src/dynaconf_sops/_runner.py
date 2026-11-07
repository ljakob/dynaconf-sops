"""Run sops to decrypt one value (D-4, D-8, D-10)."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from ._config import Config
from ._errors import SopsError
from ._reference import Reference

__all__ = ["decrypt", "first_line"]

logger = logging.getLogger("dynaconf_sops")

_MAX_STDERR = 200


def first_line(stderr: bytes) -> str:
    """First non-empty line of sops' stderr, printable ASCII-safe, truncated."""
    text = stderr.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line:
            line = "".join(ch if ch.isprintable() else "?" for ch in line)
            if len(line) > _MAX_STDERR:
                line = line[: _MAX_STDERR - 3] + "..."
            return line
    return "(no error message)"


def _fail(ref: Reference, reason: str, returncode: int | None = None) -> SopsError:
    return SopsError(
        f"@sops {ref.text}: {reason} (file {ref.file})",
        reference=ref.text,
        file=ref.file,
        path=ref.path,
        returncode=returncode,
    )


def _run(ref: Reference, config: Config, output_type: str) -> bytes:
    cmd = [config.sops_bin, "--decrypt", "--output-type", output_type]
    if ref.expr is not None:
        cmd += ["--extract", ref.expr]
    cmd.append(str(ref.file))
    # Errors are raised outside the except blocks so that no exception context
    # (which may hold partial sops output) stays attached to the SopsError.
    reason: str | None = None
    try:
        result = subprocess.run(
            cmd,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=config.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        reason = f"sops timed out after {config.timeout:g} s"
    except OSError as exc:
        reason = f"cannot run sops {config.sops_bin!r}: {exc.strerror or type(exc).__name__}"
    if reason is not None:
        raise _fail(ref, reason)
    if result.returncode != 0:
        raise _fail(
            ref,
            f"sops failed with exit code {result.returncode}: {first_line(result.stderr)}",
            result.returncode,
        )
    return result.stdout


def _text(ref: Reference, data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass  # the exception holds the value; raise outside the handler
    raise _fail(ref, "decrypted value is not valid UTF-8")


def decrypt(ref: Reference, config: Config) -> Any:
    """Decrypt the value a reference points to, keeping its type.

    sops prints strings verbatim and every other value (number, bool, null, map,
    list) through its output store. With ``--output-type yaml`` a non-string
    always ends with a newline. So: an output without a trailing newline is a
    string. Otherwise sops runs again with ``--output-type json``: identical
    bytes mean a string that ends with a newline, different bytes are parsed as
    JSON.
    """
    if not ref.file.is_file():
        raise _fail(ref, "SOPS file not found")
    logger.debug("decrypting %s path %r", ref.file, ref.path)

    if ref.expr is None:
        return _parse_json(ref, _run(ref, config, "json"))

    as_yaml = _run(ref, config, "yaml")
    if not as_yaml.endswith(b"\n"):
        return _text(ref, as_yaml)
    as_json = _run(ref, config, "json")
    if as_json == as_yaml:
        return _text(ref, as_yaml)
    return _parse_json(ref, as_json)


def _parse_json(ref: Reference, data: bytes) -> Any:
    text = _text(ref, data)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass  # the exception holds the document; raise outside the handler
    raise _fail(ref, "sops output is not valid JSON")
