"""``verify()``, ``check()`` and ``references()`` (D-11)."""

from __future__ import annotations

from typing import Any

from ._errors import SopsError
from ._walk import describe, is_reference_lazy, is_reference_string, iter_items

__all__ = ["check", "references", "verify"]


def _store(settings: Any) -> Any:
    return settings.store  # triggers setup of LazySettings


def references(settings: Any) -> dict[str, str]:
    """Map each setting that holds a ``@sops`` reference to the reference text.

    Keys are dotted paths in Dynaconf's spelling: the top-level key is upper
    case (Dynaconf normalises it and does not keep the original spelling),
    nested keys are exactly as written, list items appear as ``[i]``. Example:
    ``{"DATABASE.password": "@sops mariadb:users.app.password",
    "DATABASE.replicas[0]": "@sops mariadb:replica.password"}``.
    Nothing is decrypted; the result never contains a value.
    """
    return {
        item.path: describe(item.value)
        for item in iter_items(_store(settings))
        if is_reference_lazy(item.value) or is_reference_string(item.value)
    }


def _resolve_all(settings: Any) -> tuple[int, dict[str, SopsError]]:
    failures: dict[str, SopsError] = {}
    count = 0
    for item in iter_items(_store(settings)):
        if is_reference_lazy(item.value):
            count += 1
            try:
                item.value(settings)
            except SopsError as exc:
                failures[item.path] = exc
        elif is_reference_string(item.value):
            count += 1
            failures[item.path] = SopsError(
                f"{item.value!r} was not converted: import dynaconf_sops before "
                "the settings are loaded or add 'dynaconf_sops.loader' to "
                "LOADERS_FOR_DYNACONF",
                reference=item.value[len("@sops") :].strip(),
            )
    return count, failures


def check(settings: Any) -> dict[str, SopsError]:
    """Resolve every ``@sops`` reference once and return the failures by key.

    Like ``verify()``, but nothing is raised for reference problems: the result
    maps each failing key (same format as ``references()``) to its
    ``SopsError``; an empty dict means every reference resolved. Successful
    values are cached and stay in the settings; the result never contains a
    value. Use it to load everything and report broken references per key.
    """
    return _resolve_all(settings)[1]


def verify(settings: Any) -> int:
    """Resolve every ``@sops`` reference once (fail fast at service start).

    Successful values are cached, so later access does not run sops again.
    ``verify()`` is ``check()`` plus one aggregated error.

    Returns:
        The number of references resolved.

    Raises:
        SopsError: one error listing every failing reference (in ``errors``).
            A ``"@sops ..."`` string that was never converted (the converter
            was registered after the settings were loaded and the loader is
            not active) counts as a failure.
    """
    count, failures = _resolve_all(settings)
    if failures:
        lines = [f"{len(failures)} of {count} @sops reference(s) failed:"]
        lines += [f"  {path}: {exc}" for path, exc in failures.items()]
        raise SopsError("\n".join(lines), errors=list(failures.values()))
    return count
