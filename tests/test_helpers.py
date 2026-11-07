from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from dynaconf import Dynaconf
from dynaconf.utils.parse_conf import converters

import dynaconf_sops
from dynaconf_sops import SopsError

from .conftest import CountingSops, MakeSops

Write = Callable[[str, str], Path]

SECRETS = """\
users:
  app: {user: app, password: app-pw}
  other: {password: other-pw}
api: {token: tok-123, ids: [1, 2]}
"""


@pytest.fixture
def secrets(make_sops: MakeSops, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = make_sops("mariadb.sops.yaml", SECRETS, directory=tmp_path / "sops")
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(path.parent))
    return path


SETTINGS = """\
token: "@sops mariadb:api.token"
database:
  user: app
  password: "@sops mariadb:users.app.password"
  combo: "@sops @format {env[DYNACONF_SOPS_DIR]}/mariadb.sops.yaml#users.other.password"
  list: ["@sops mariadb:api.ids", plain]
plain: value
"""


def test_references_lists_without_decrypting(write: Write, counting_sops: CountingSops) -> None:
    settings = Dynaconf(settings_files=[write("s.yaml", SETTINGS)])
    refs = dynaconf_sops.references(settings)
    assert refs == {
        "TOKEN": "@sops mariadb:api.token",
        "DATABASE.password": "@sops mariadb:users.app.password",
        "DATABASE.combo": (
            "@sops @format {env[DYNACONF_SOPS_DIR]}/mariadb.sops.yaml#users.other.password"
        ),
        "DATABASE.list[0]": "@sops mariadb:api.ids",
    }
    assert counting_sops.calls() == []


def test_references_empty(write: Write) -> None:
    settings = Dynaconf(settings_files=[write("s.yaml", "a: 1\nb: {c: [1, 2]}\n")])
    assert dynaconf_sops.references(settings) == {}
    assert dynaconf_sops.verify(settings) == 0


def test_verify_all_good(write: Write, secrets: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = Dynaconf(settings_files=[write("s.yaml", SETTINGS)])
    with caplog.at_level(logging.DEBUG, logger="dynaconf_sops"):
        assert dynaconf_sops.verify(settings) == 4
    assert dynaconf_sops.secret_values() == {"tok-123", "app-pw", "other-pw"}
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="dynaconf_sops"):
        assert settings.database.password == "app-pw"
        assert list(settings.database.list[0]) == [1, 2]
    assert caplog.records == []  # served from the cache, sops not run again


def test_verify_collects_all_failures(write: Write, secrets: Path, tmp_path: Path) -> None:
    content = (
        SETTINGS
        + 'bad1: "@sops mariadb:users.nobody.password"\n'
        + f'bad2: "@sops {tmp_path}/missing.sops.yaml#x"\n'
        + 'bad3: "@sops not a reference"\n'
    )
    settings = Dynaconf(settings_files=[write("s.yaml", content)])
    with pytest.raises(SopsError) as info:
        dynaconf_sops.verify(settings)
    err = info.value
    assert len(err.errors) == 3
    msg = str(err)
    assert msg.startswith("3 of 7 @sops reference(s) failed:")
    assert "BAD1: @sops mariadb:users.nobody.password" in msg
    assert "BAD2: " in msg
    assert "missing.sops.yaml" in msg
    assert "BAD3: invalid @sops reference 'not a reference'" in msg
    for secret in ("app-pw", "other-pw", "tok-123"):
        assert secret not in msg
    assert {e.returncode for e in err.errors} == {1, None}


def test_verify_reports_unconverted_strings(write: Write, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(converters, "@sops")
    settings = Dynaconf(settings_files=[write("s.yaml", 'db:\n  password: "@sops x:y"\n')])
    assert settings.db.password == "@sops x:y"
    assert dynaconf_sops.references(settings) == {"DB.password": "@sops x:y"}
    with pytest.raises(SopsError, match="was not converted") as info:
        dynaconf_sops.verify(settings)
    assert info.value.errors[0].reference == "x:y"


def test_secret_values_feed_a_redaction_filter(
    write: Write, secrets: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = Dynaconf(settings_files=[write("s.yaml", SETTINGS)])
    password = settings.database.password

    class Redact(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            message = record.getMessage()
            for secret in dynaconf_sops.secret_values():
                message = message.replace(secret, "***")
            record.msg, record.args = message, None
            return True

    logger = logging.getLogger("test.redact")
    logger.addFilter(Redact())
    with caplog.at_level(logging.INFO, logger="test.redact"):
        logger.info("connecting with %s", password)
    assert caplog.messages == ["connecting with ***"]
