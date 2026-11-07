"""Loader activation (P3.1). Laziness and edge cases are in test_loader_lazy.py."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from dynaconf import Dynaconf
from dynaconf.utils.parse_conf import Lazy, converters

import dynaconf_sops

from .conftest import LOADERS, MakeSops

Write = Callable[[str, str], Path]

SECRETS = """\
users:
  app: {user: app, password: app-pw}
  other: {password: other-pw}
root_password: root-pw
port: 3306
"""

BODY = """\
token: "@sops mariadb:root_password"
database:
  user: app
  password: "@sops mariadb:users.app.password"
  port: "@sops mariadb:port"
  combo: "@sops @format {env[DYNACONF_SOPS_DIR]}/mariadb.sops.yaml#users.other.password"
  list: ["@sops mariadb:users.other.password", plain]
plain: value
"""


@pytest.fixture
def secrets(make_sops: MakeSops, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = make_sops("mariadb.sops.yaml", SECRETS, directory=tmp_path / "sops")
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(path.parent))
    return path


def _check(settings: Dynaconf) -> None:
    assert settings.plain == "value"
    assert settings.token == "root-pw"
    assert settings.database.user == "app"
    assert settings.database.password == "app-pw"
    assert settings.database.port == 3306
    assert settings.database.combo == "other-pw"
    assert list(settings.database.list) == ["other-pw", "plain"]


def test_without_loader_strings_stay_plain(write: Write, unregistered: None) -> None:
    settings = Dynaconf(settings_files=[write("s.yaml", BODY)])
    assert settings.database.password == "@sops mariadb:users.app.password"


def test_loader_in_settings_file(write: Write, secrets: Path, unregistered: None) -> None:
    cfg = write("s.yaml", f"LOADERS_FOR_DYNACONF: {LOADERS}\n{BODY}")
    settings = Dynaconf(settings_files=[cfg])
    raw = dict.__getitem__(settings.store, "DATABASE")
    assert isinstance(dict.__getitem__(raw, "password"), Lazy)
    _check(settings)
    assert "@sops" in converters


def test_loader_from_environment(
    write: Write, secrets: Path, unregistered: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOADERS_FOR_DYNACONF", LOADERS)
    settings = Dynaconf(settings_files=[write("s.yaml", BODY)], envvar_prefix="APP")
    _check(settings)


def test_loader_kwarg(write: Write, secrets: Path, unregistered: None) -> None:
    settings = Dynaconf(
        settings_files=[write("s.yaml", BODY)],
        loaders=["dynaconf.loaders.env_loader", "dynaconf_sops.loader"],
    )
    _check(settings)


def test_loader_with_converter_already_registered(write: Write, secrets: Path) -> None:
    dynaconf_sops.register()
    cfg = write("s.yaml", f"LOADERS_FOR_DYNACONF: {LOADERS}\n{BODY}")
    _check(Dynaconf(settings_files=[cfg]))


def test_env_values_converted(
    write: Write, secrets: Path, unregistered: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DATABASE__EXTRA", "@sops mariadb:users.other.password")
    monkeypatch.setenv("APP_SECRET", "@sops mariadb:root_password")
    monkeypatch.setenv("APP_DATABASE__USER", "env-user")
    cfg = write("s.yaml", f"LOADERS_FOR_DYNACONF: {LOADERS}\n{BODY}")
    settings = Dynaconf(settings_files=[cfg], envvar_prefix="APP")
    assert settings.database.extra == "other-pw"
    assert settings.secret == "root-pw"
    assert settings.database.user == "env-user"
    assert settings.database.password == "app-pw"


def test_env_loader_still_active(
    write: Write, secrets: Path, unregistered: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_PLAIN", "overridden")
    cfg = write("s.yaml", f"LOADERS_FOR_DYNACONF: {LOADERS}\n{BODY}")
    settings = Dynaconf(settings_files=[cfg], envvar_prefix="APP")
    assert settings.plain == "overridden"


def test_environments_in_default_section(write: Write, secrets: Path, unregistered: None) -> None:
    cfg = write(
        "s.yaml",
        f"""\
default:
  LOADERS_FOR_DYNACONF: {LOADERS}
  database:
    password: "@sops mariadb:users.app.password"
development:
  database:
    user: dev
    password: "@sops mariadb:users.other.password"
""",
    )
    settings = Dynaconf(settings_files=[cfg], environments=True)
    assert settings.database.password == "other-pw"
    assert settings.database.user == "dev"
    prod = Dynaconf(settings_files=[cfg], environments=True, env="production")
    assert prod.database.password == "app-pw"


def test_inspect_history_shows_reference(write: Write, secrets: Path, unregistered: None) -> None:
    cfg = write("s.yaml", f"LOADERS_FOR_DYNACONF: {LOADERS}\n{BODY}")
    settings = Dynaconf(settings_files=[cfg])
    history = getattr(settings, "loaded_by_loaders", None)  # 3.3
    if history is None:  # pragma: no cover - 3.2
        history = settings._loaded_by_loaders
    loaded = {meta.loader: data for meta, data in history.items()}
    assert "dynaconf_sops" in loaded
    assert repr(loaded["dynaconf_sops"]["TOKEN"]) == "'@@sops mariadb:root_password'"
