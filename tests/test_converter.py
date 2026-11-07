from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from dynaconf import Dynaconf
from dynaconf.utils.parse_conf import converters

import dynaconf_sops
from dynaconf_sops import SopsError, _converter

from .conftest import DYNACONF_VERSION, CountingSops, MakeSops

Write = Callable[[str, str], Path]

SECRETS = """\
users:
  app:
    user: app
    password: app-pw
  other:
    password: other-pw
root_password: root-pw
port: 3306
list: [a, b]
"""


@pytest.fixture
def secrets(make_sops: MakeSops, tmp_path: Path) -> Path:
    return make_sops("mariadb.sops.yaml", SECRETS, directory=tmp_path / "sops")


def _touch(tmp_path: Path, name: str = "mariadb.sops.yaml") -> Path:
    d = tmp_path / "sops"
    d.mkdir(exist_ok=True)
    (d / name).write_text("placeholder: true\n")
    return d


def test_import_registers() -> None:
    assert "@sops" in converters
    assert converters["@sops"].__name__ == "sops"


def test_register_idempotent() -> None:
    before = converters["@sops"]
    dynaconf_sops.register()
    dynaconf_sops.register()
    assert converters["@sops"] is before


def test_register_configures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counting_sops: CountingSops
) -> None:
    d = _touch(tmp_path)
    monkeypatch.delenv("DYNACONF_SOPS_BIN")
    dynaconf_sops.register(sops_dir=d, sops_bin=counting_sops.bin, timeout=5)
    assert _converter.resolve("mariadb:users.app.password") == 'value-["users"]["app"]["password"]'
    dynaconf_sops.register()  # no arguments keep the configuration
    assert _converter._settings.sops_dir == d
    assert _converter._settings.timeout == 5


def test_register_beats_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counting_sops: CountingSops
) -> None:
    d = _touch(tmp_path)
    monkeypatch.setenv("DYNACONF_SOPS_DIR", "/nonexistent")
    dynaconf_sops.register(sops_dir=d)
    assert _converter.resolve("mariadb:a") == 'value-["a"]'


def test_values_with_real_sops(
    secrets: Path, write: Write, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(secrets.parent))
    cfg = write(
        "settings.yaml",
        f"""\
database:
  user: app
  password: "@sops mariadb:users.app.password"
  port: "@sops mariadb:port"
  explicit: "@sops {secrets}#root_password"
  whole_user: "@sops mariadb:users.app"
  items: "@sops mariadb:list"
plain: value
""",
    )
    settings = Dynaconf(settings_files=[cfg])
    assert settings.database.password == "app-pw"
    assert settings.database.port == 3306
    assert settings.database.explicit == "root-pw"
    assert settings.database.whole_user == {"user": "app", "password": "app-pw"}
    assert type(settings.database.whole_user) is dict  # plain dict, no attribute access
    assert list(settings.database["items"]) == ["a", "b"]
    assert settings.get("database.password") == "app-pw"
    assert settings["database"]["password"] == "app-pw"
    assert settings.plain == "value"


def test_lazy_until_access(write: Write, tmp_path: Path, counting_sops: CountingSops) -> None:
    d = _touch(tmp_path)
    cfg = write(
        "settings.yaml",
        f"""\
token: "@sops {d}/mariadb.sops.yaml#token"
database:
  user: app
  password: "@sops {d}/mariadb.sops.yaml#users.app.password"
  other: "@sops {d}/mariadb.sops.yaml#users.other.password"
  nested:
    deep: "@sops {d}/mariadb.sops.yaml#deep"
  many: ["@sops {d}/mariadb.sops.yaml#l.0", plain, "@sops {d}/mariadb.sops.yaml#l.1"]
""",
    )
    settings = Dynaconf(settings_files=[cfg])
    assert settings.database.user == "app"
    assert settings.get("database.nested") is not None
    assert counting_sops.calls() == []
    assert settings.database.password == 'value-["users"]["app"]["password"]'
    assert len(counting_sops.calls()) == 1
    assert settings.database.password == 'value-["users"]["app"]["password"]'
    assert len(counting_sops.calls()) == 1
    assert settings.database.nested.deep == 'value-["deep"]'
    assert list(settings.database.many) == ['value-["l"][0]', "plain", 'value-["l"][1]']
    assert settings.token == 'value-["token"]'
    assert len(counting_sops.calls()) == 5


@pytest.mark.parametrize(
    ("raw", "expected_file"),
    [
        ('"@sops @format {env[SECRETS_HOME]}/mariadb.sops.yaml#a.b"', "mariadb.sops.yaml"),
        ('"@sops @jinja {{ this.SECRETS_DIR }}/mariadb.sops.yaml#a.b"', "mariadb.sops.yaml"),
        pytest.param(
            '"@sops @get REF"',
            "mariadb.sops.yaml",
            marks=pytest.mark.skipif(
                DYNACONF_VERSION < (3, 3, 0), reason="Dynaconf 3.2 combines only @format/@jinja"
            ),
        ),
    ],
)
def test_combined_with_lazy_formatters(
    raw: str,
    expected_file: str,
    write: Write,
    tmp_path: Path,
    counting_sops: CountingSops,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = _touch(tmp_path)
    monkeypatch.setenv("SECRETS_HOME", str(d))
    cfg = write(
        "settings.yaml",
        f'secrets_dir: "{d}"\nref: "{d}/mariadb.sops.yaml#a.b"\nvalue: {raw}\n',
    )
    settings = Dynaconf(settings_files=[cfg])
    assert counting_sops.calls() == []
    assert settings.value == 'value-["a"]["b"]'
    assert counting_sops.calls()[0].endswith(f"{d}/{expected_file}")


def test_value_from_env_var(secrets: Path, write: Write, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(secrets.parent))
    monkeypatch.setenv("APP_DATABASE__PASSWORD", "@sops mariadb:users.other.password")
    monkeypatch.setenv("APP_TOKEN", "@sops mariadb:root_password")
    cfg = write("settings.yaml", "database:\n  user: app\n")
    settings = Dynaconf(settings_files=[cfg], envvar_prefix="APP")
    assert settings.database.password == "other-pw"
    assert settings.database.user == "app"
    assert settings.token == "root-pw"


def test_env_override_of_reference(
    secrets: Path, write: Write, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(secrets.parent))
    monkeypatch.setenv("APP_DATABASE__PASSWORD", "from-env")
    monkeypatch.setenv("APP_TOKEN", "token-from-env")
    cfg = write(
        "settings.yaml",
        'token: "@sops mariadb:root_password"\n'
        'database:\n  password: "@sops mariadb:users.app.password"\n',
    )
    settings = Dynaconf(settings_files=[cfg], envvar_prefix="APP")
    assert settings.database.password == "from-env"
    assert settings.token == "token-from-env"


def test_environments_and_merge(
    secrets: Path, write: Write, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(secrets.parent))
    cfg = write(
        "settings.yaml",
        """\
default:
  database:
    user: app
    password: "@sops mariadb:users.app.password"
development:
  database:
    password: "@sops mariadb:users.other.password"
production:
  database:
    user: prod
""",
    )
    dev = Dynaconf(settings_files=[cfg], environments=True, merge_enabled=True)
    assert dev.database.password == "other-pw"
    assert dev.database.user == "app"
    prod = Dynaconf(settings_files=[cfg], environments=True, merge_enabled=True, env="production")
    assert prod.database.user == "prod"
    assert prod.database.password == "app-pw"


def test_error_on_access_not_load(write: Write, tmp_path: Path) -> None:
    cfg = write(
        "settings.yaml",
        f'plain: ok\nbroken: "@sops {tmp_path}/missing.sops.yaml#a"\ninvalid: "@sops nonsense"\n',
    )
    settings = Dynaconf(settings_files=[cfg])
    assert settings.plain == "ok"
    with pytest.raises(SopsError, match="SOPS file not found"):
        _ = settings.broken
    with pytest.raises(SopsError, match="invalid @sops reference 'nonsense'"):
        _ = settings.invalid


def test_plain_values_untouched(write: Write) -> None:
    cfg = write("settings.yaml", 'b: "mail@sops.example"\nc: 1\n')
    settings = Dynaconf(settings_files=[cfg])
    assert settings.b == "mail@sops.example"
    assert settings.c == 1


@pytest.mark.skipif(DYNACONF_VERSION < (3, 3, 2), reason="see test_prefix_crash_before_332")
def test_token_prefix_is_not_a_token(write: Write) -> None:
    settings = Dynaconf(settings_files=[write("settings.yaml", 'a: "@sopsy not a token"\n')])
    assert settings.a == "@sopsy not a token"


@pytest.mark.skipif(DYNACONF_VERSION >= (3, 3, 2), reason="fixed in Dynaconf 3.3.2")
def test_prefix_crash_before_332(write: Write) -> None:
    # Dynaconf < 3.3.2 matches converters with str.startswith: any registered token
    # (also built-ins such as @int) breaks strings like "@intx". Documented.
    settings = Dynaconf(settings_files=[write("settings.yaml", 'a: "@sopsy not a token"\n')])
    with pytest.raises(KeyError):
        _ = settings.a


class TestSopsDirMessages:
    """W1 (consumer feedback): the shorthand needs a sops dir, messages name its source."""

    def test_shorthand_without_sops_dir_fails_on_access(self, write: Write) -> None:
        cfg = write("s.yaml", 'plain: ok\npw: "@sops mariadb:users.app.password"\n')
        settings = Dynaconf(settings_files=[cfg])
        assert settings.plain == "ok"
        with pytest.raises(SopsError, match="DYNACONF_SOPS_DIR is not set"):
            _ = settings.pw

    def test_explicit_relative_path_still_uses_cwd(
        self,
        write: Write,
        tmp_path: Path,
        counting_sops: CountingSops,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "local.sops.yaml").write_text("x: 1\n")
        monkeypatch.chdir(tmp_path)
        cfg = write("s.yaml", 'pw: "@sops local.sops.yaml#a"\n')
        assert Dynaconf(settings_files=[cfg]).pw == 'value-["a"]'

    def test_missing_sops_dir_named_with_source(
        self, write: Write, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DYNACONF_SOPS_DIR", str(tmp_path / "typo"))
        settings = Dynaconf(settings_files=[write("s.yaml", 'pw: "@sops mariadb:a"\n')])
        with pytest.raises(SopsError) as info:
            _ = settings.pw
        assert f"sops dir {tmp_path / 'typo'} (from DYNACONF_SOPS_DIR) does not exist" in str(
            info.value
        )

    def test_file_not_found_names_sops_dir_and_source(self, write: Write, tmp_path: Path) -> None:
        d = tmp_path / "sops"
        d.mkdir()
        dynaconf_sops.register(sops_dir=d)
        settings = Dynaconf(settings_files=[write("s.yaml", 'pw: "@sops mariadb:a"\n')])
        with pytest.raises(SopsError) as info:
            _ = settings.pw
        assert f"SOPS file not found (sops dir {d} from register(sops_dir=...))" in str(info.value)

    def test_verify_reports_missing_sops_dir_per_key(self, write: Write) -> None:
        cfg = write("s.yaml", 'a: "@sops mariadb:x"\nb: plain\n')
        with pytest.raises(SopsError) as info:
            dynaconf_sops.verify(Dynaconf(settings_files=[cfg]))
        assert "A: @sops mariadb:x: the shorthand 'name:path' needs a sops dir" in str(info.value)
