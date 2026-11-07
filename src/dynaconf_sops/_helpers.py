"""``verify()`` and ``references()`` (D-11)."""

from __future__ import annotations

from typing import Any

from ._errors import SopsError
from ._walk import describe, is_reference_lazy, is_reference_string, iter_items

__all__ = ["references", "verify"]


def _store(settings: Any) -> Any:
    return settings.store  # triggers setup of LazySettings


def references(settings: Any) -> dict[str, str]:
    """Map each setting that holds a ``@sops`` reference to the reference text.

    Keys are dotted paths as stored by Dynaconf (top-level keys upper case, list
    items as ``[i]``), e.g. ``{"DATABASE.password": "@sops mariadb:users.app.password"}``.
    Nothing is decrypted; the result never contains a value.
    """
    return {
        item.path: describe(item.value)
        for item in iter_items(_store(settings))
        if is_reference_lazy(item.value) or is_reference_string(item.value)
    }


def verify(settings: Any) -> int:
    """Resolve every ``@sops`` reference once (fail fast at service start).

    Successful values are cached, so later access does not run sops again.

    Returns:
        The number of references resolved.

    Raises:
        SopsError: one error listing every failing reference (in ``errors``).
            A ``"@sops ..."`` string that was never converted (the converter
            was registered after the settings were loaded and the loader is
            not active) counts as a failure.
    """
    failures: list[tuple[str, SopsError]] = []
    count = 0
    for item in iter_items(_store(settings)):
        if is_reference_lazy(item.value):
            count += 1
            try:
                item.value(settings)
            except SopsError as exc:
                failures.append((item.path, exc))
        elif is_reference_string(item.value):
            count += 1
            failures.append(
                (
                    item.path,
                    SopsError(
                        f"{item.value!r} was not converted: import dynaconf_sops before "
                        "the settings are loaded or add 'dynaconf_sops.loader' to "
                        "LOADERS_FOR_DYNACONF",
                        reference=item.value[len("@sops") :].strip(),
                    ),
                )
            )
    if failures:
        lines = [f"{len(failures)} of {count} @sops reference(s) failed:"]
        lines += [f"  {path}: {exc}" for path, exc in failures]
        raise SopsError("\n".join(lines), errors=[exc for _, exc in failures])
    return count
