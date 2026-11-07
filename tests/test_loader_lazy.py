"""Loader laziness and edge cases (P3.2).

``counting_sops`` is a stub that logs every call, so ``calls() == []`` proves
that nothing was decrypted.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from dynaconf import Dynaconf, Validator

import dynaconf_sops
from dynaconf_sops import SopsError, _config

from .conftest import LOADERS, CountingSops

Write = Callable[[str, str], Path]


@pytest.fixture
def sops_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "sops"
    d.mkdir()
    (d / "mariadb.sops.yaml").write_text("placeholder: true\n")
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(d))
    return d


SETTINGS = f"""\
LOADERS_FOR_DYNACONF: {LOADERS}
token: "@sops mariadb:token"
database:
  user: app
  password: "@sops mariadb:users.app.password"
  root: "@sops mariadb:root_password"
  nested:
    deep: "@sops mariadb:deep.value"
    list: ["@sops mariadb:list.0", plain, "@sops mariadb:list.1"]
  combo: "@sops @format {{env[DYNACONF_SOPS_DIR]}}/mariadb.sops.yaml#combo"
other:
  name: x
"""


def _load(write: Write, **kwargs: object) -> Dynaconf:
    settings = Dynaconf(settings_files=[write("s.yaml", SETTINGS)], envvar_prefix="APP", **kwargs)
    settings.get("other.name")  # force setup
    return settings


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"merge_enabled": True}, {"environments": False, "dotted_lookup": True}],
    ids=["plain", "merge_enabled", "dotted"],
)
def test_zero_calls_during_load(
    write: Write,
    sops_dir: Path,
    counting_sops: CountingSops,
    unregistered: None,
    kwargs: dict[str, object],
) -> None:
    settings = _load(write, **kwargs)
    assert settings.database.user == "app"
    assert settings.other.name == "x"
    assert counting_sops.calls() == []
    assert settings.database.password == 'value-["users"]["app"]["password"]'
    assert len(counting_sops.calls()) == 1
    assert settings.database.nested.deep == 'value-["deep"]["value"]'
    assert len(counting_sops.calls()) == 2


def test_zero_calls_with_env_overrides(
    write: Write,
    sops_dir: Path,
    counting_sops: CountingSops,
    unregistered: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATABASE__USER", "env-user")
    monkeypatch.setenv("APP_DATABASE__NESTED__EXTRA", "@sops mariadb:extra")
    monkeypatch.setenv("APP_TOKEN", "@sops mariadb:env_token")
    settings = _load(write)
    assert settings.database.user == "env-user"
    assert counting_sops.calls() == []
    assert settings.token == 'value-["env_token"]'
    assert settings.database.nested.extra == 'value-["extra"]'
    assert settings.database.password == 'value-["users"]["app"]["password"]'


def test_zero_calls_with_environments(
    write: Write, sops_dir: Path, counting_sops: CountingSops, unregistered: None
) -> None:
    cfg = write(
        "s.yaml",
        f"""\
default:
  LOADERS_FOR_DYNACONF: {LOADERS}
  database:
    user: app
    password: "@sops mariadb:default.password"
    other: "@sops mariadb:default.other"
development:
  database:
    password: "@sops mariadb:dev.password"
""",
    )
    settings = Dynaconf(settings_files=[cfg], environments=True, merge_enabled=True)
    assert settings.database.user == "app"
    assert counting_sops.calls() == []
    assert settings.database.password == 'value-["dev"]["password"]'
    assert len(counting_sops.calls()) == 1


def test_reload_stays_lazy(
    write: Write, sops_dir: Path, counting_sops: CountingSops, unregistered: None
) -> None:
    settings = _load(write)
    assert settings.database.password == 'value-["users"]["app"]["password"]'
    settings.reload()
    settings.get("other.name")
    assert len(counting_sops.calls()) == 1
    assert settings.database.password == 'value-["users"]["app"]["password"]'
    assert settings.database.root == 'value-["root_password"]'
    assert len(counting_sops.calls()) == 2  # password came from the cache


def test_no_references_no_calls(
    write: Write, counting_sops: CountingSops, unregistered: None
) -> None:
    cfg = write("s.yaml", f"LOADERS_FOR_DYNACONF: {LOADERS}\na: 1\nb: {{c: [x, y]}}\n")
    settings = Dynaconf(settings_files=[cfg])
    assert settings.b.c == ["x", "y"]
    assert counting_sops.calls() == []
    assert dynaconf_sops.references(settings) == {}


def test_container_mode_plaintext_without_sops(
    write: Write, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unregistered: None
) -> None:
    """Rendered plaintext settings, no sops anywhere, no key: the package is inert."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(_config, "FALLBACK_BINARIES", ())
    cfg = write(
        "s.yaml",
        f"LOADERS_FOR_DYNACONF: {LOADERS}\ndatabase:\n  user: app\n  password: rendered-pw\n",
    )
    settings = Dynaconf(settings_files=[cfg])
    assert settings.database.password == "rendered-pw"
    assert dynaconf_sops.verify(settings) == 0


def test_missing_sops_fails_on_access_only(
    write: Write,
    sops_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unregistered: None,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(_config, "FALLBACK_BINARIES", ())
    settings = _load(write)
    assert settings.database.user == "app"
    with pytest.raises(SopsError, match="sops binary not found"):
        _ = settings.database.password


# --- Dynaconf behaviour we cannot control (pinned, documented in docs/security.md) ---
#
# Every dotted set into a section (validators call setdefault(), settings.set(),
# in import mode also an env override of a sibling) makes Dynaconf merge the
# section. Depending on the Dynaconf version (observed on 3.2.x and 3.3.3+, not
# on 3.3.0-3.3.2) the merge evaluates the lazy values of that section. The
# library cannot prevent it without patching Dynaconf (D-6); the cache
# guarantees at most one sops call per reference and other sections stay
# untouched. These tests pin exactly that, on every supported version.

SECTION_REFS = {
    '["users"]["app"]["password"]',
    '["root_password"]',
    '["deep"]["value"]',
    '["list"][0]',
    '["list"][1]',
    '["combo"]',
}


def _extracts(calls: list[str]) -> list[str]:
    return [c.split("--extract ", 1)[1].rsplit(" ", 1)[0] for c in calls]


def _assert_section_only(counting_sops: CountingSops) -> None:
    extracts = _extracts(counting_sops.calls())
    assert len(extracts) == len(set(extracts)), "a reference was decrypted twice"
    assert set(extracts) <= SECTION_REFS, "a reference outside the section was decrypted"


def test_validator_on_other_section_does_not_decrypt(
    write: Write, sops_dir: Path, counting_sops: CountingSops, unregistered: None
) -> None:
    settings = Dynaconf(
        settings_files=[write("s.yaml", SETTINGS)],
        validators=[Validator("other.name", must_exist=True), Validator("PORT", default=1)],
    )
    assert settings.other.name == "x"
    assert counting_sops.calls() == []


def test_validator_in_section_decrypts_at_most_that_section(
    write: Write, sops_dir: Path, counting_sops: CountingSops, unregistered: None
) -> None:
    settings = Dynaconf(
        settings_files=[write("s.yaml", SETTINGS)],
        validators=[Validator("database.user", must_exist=True)],
    )
    settings.get("other.name")
    _assert_section_only(counting_sops)


def test_runtime_set_in_section_decrypts_at_most_that_section(
    write: Write, sops_dir: Path, counting_sops: CountingSops, unregistered: None
) -> None:
    settings = _load(write)
    settings.set("other.name", "y")
    assert counting_sops.calls() == []
    settings.set("database.user", "changed")
    _assert_section_only(counting_sops)
    assert settings.database.user == "changed"


def test_import_mode_env_sibling_override(
    write: Write,
    sops_dir: Path,
    counting_sops: CountingSops,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With the converter imported, the values are already lazy when the env
    # loader merges APP_DATABASE__USER into the section. Loader mode avoids it
    # (test_zero_calls_with_env_overrides).
    monkeypatch.setenv("APP_DATABASE__USER", "env-user")
    dynaconf_sops.register()
    settings = _load(write)
    _assert_section_only(counting_sops)
    assert settings.database.user == "env-user"
