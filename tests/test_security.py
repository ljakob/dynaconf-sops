"""D-12: secret values never appear in argv, exceptions, logs, repr() or files."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from dynaconf import Dynaconf

import dynaconf_sops
from dynaconf_sops import SopsError
from dynaconf_sops._config import Config
from dynaconf_sops._reference import parse_reference
from dynaconf_sops._runner import decrypt

from .conftest import LOADERS, AgeKeys, MakeSops, write_stub

Write = Callable[[str, str], Path]

SECRET = "s3cr3t-Value-0xDEADBEEF"
SIBLING = "sibling-Secret-42"
SECRETS_YAML = f"""\
db:
  password: {SECRET}
  sibling: {SIBLING}
  map: {{inner: {SECRET}}}
num: 12345
"""


@pytest.fixture
def secrets(make_sops: MakeSops, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = make_sops("app.sops.yaml", SECRETS_YAML, directory=tmp_path / "sops")
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(path.parent))
    return path


@pytest.fixture
def recorded_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every subprocess.run call made by the library."""
    calls: list[dict[str, Any]] = []
    real_run = subprocess.run

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, "kwargs": kwargs})
        return real_run(*args, **kwargs)

    monkeypatch.setattr("dynaconf_sops._runner.subprocess.run", spy)
    return calls


def _all_text(exc: BaseException) -> str:
    """Everything an exception exposes: message, repr, attributes, chained exceptions."""
    parts = [str(exc), repr(exc), repr(vars(exc))]
    if exc.__cause__ is not None:
        parts.append(_all_text(exc.__cause__))
    if exc.__context__ is not None:
        parts.append(_all_text(exc.__context__))
    for sub in getattr(exc, "errors", ()):
        parts.append(_all_text(sub))
    return "\n".join(parts)


def _tree(root: Path) -> set[tuple[str, int, int]]:
    return {
        (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file() and "sops-calls" not in p.name
    }


def test_argv_contains_only_flags_expression_and_file(
    secrets: Path, recorded_runs: list[dict[str, Any]], sops_bin: str
) -> None:
    for path in ("db.password", "db.map", "num", ""):
        dynaconf_sops.clear_cache()
        cfg = Config(sops_dir=None, sops_bin=sops_bin, timeout=30)
        decrypt(parse_reference(f"{secrets}#{path}"), cfg)
    assert recorded_runs
    for call in recorded_runs:
        argv = call["args"][0]
        kwargs = call["kwargs"]
        assert kwargs["shell"] is False
        assert "env" not in kwargs  # inherited environment
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert argv[0] == sops_bin
        assert argv[-1] == str(secrets)
        allowed = {"--decrypt", "--output-type", "yaml", "json", "--extract"}
        for arg in argv[1:-1]:
            assert arg in allowed or arg.startswith("["), arg
        joined = " ".join(argv)
        assert SECRET not in joined
        assert SIBLING not in joined


def test_value_from_settings_never_in_argv(
    secrets: Path, recorded_runs: list[dict[str, Any]], write: Write
) -> None:
    cfg = write("s.yaml", 'db:\n  password: "@sops app:db.password"\n')
    settings = Dynaconf(settings_files=[cfg])
    assert settings.db.password == SECRET
    assert all(SECRET not in " ".join(c["args"][0]) for c in recorded_runs)


@pytest.mark.parametrize(
    "path",
    ["db.password.deeper", "db.nope", "db.map.inner.x", "num.x"],
)
def test_error_messages_contain_no_values(secrets: Path, sops_bin: str, path: str) -> None:
    cfg = Config(sops_dir=None, sops_bin=sops_bin, timeout=30)
    with pytest.raises(SopsError) as info:
        decrypt(parse_reference(f"{secrets}#{path}"), cfg)
    text = _all_text(info.value)
    assert SECRET not in text
    assert SIBLING not in text
    assert "12345" not in text
    assert info.value.__context__ is None


def test_wrong_key_error_contains_no_values(
    secrets: Path, sops_bin: str, age_keys: AgeKeys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(age_keys.other_key_file))
    with pytest.raises(SopsError) as info:
        decrypt(
            parse_reference(f"{secrets}#db.password"),
            Config(sops_dir=None, sops_bin=sops_bin, timeout=30),
        )
    assert SECRET not in _all_text(info.value)


@pytest.mark.parametrize(
    ("script", "fragment"),
    [
        (f"printf '{SECRET}\\377\\n'", "not valid UTF-8"),
        (f"printf '{{\"{SECRET}\": oops\\n'", "not valid JSON"),
    ],
)
def test_decode_errors_drop_the_output(tmp_path: Path, script: str, fragment: str) -> None:
    stub = write_stub(tmp_path / "sops", script)
    target = tmp_path / "x.sops.yaml"
    target.write_text("a: 1\n")
    path = "" if "JSON" in fragment else "a"
    with pytest.raises(SopsError, match=fragment) as info:
        decrypt(parse_reference(f"{target}#{path}"), Config(None, str(stub), 5))
    assert info.value.__context__ is None
    assert info.value.__cause__ is None
    assert SECRET not in _all_text(info.value)


def test_timeout_error_drops_partial_output(tmp_path: Path) -> None:
    stub = write_stub(tmp_path / "sops", f"printf '{SECRET}'; sleep 5")
    target = tmp_path / "x.sops.yaml"
    target.write_text("a: 1\n")
    with pytest.raises(SopsError, match="timed out") as info:
        decrypt(parse_reference(f"{target}#a"), Config(None, str(stub), 0.3))
    assert info.value.__context__ is None
    assert SECRET not in _all_text(info.value)


def test_verify_error_contains_no_values(secrets: Path, write: Write) -> None:
    cfg = write(
        "s.yaml",
        'ok: "@sops app:db.password"\nbad: "@sops app:db.password.x"\nbad2: "@sops app:nope"\n',
    )
    settings = Dynaconf(settings_files=[cfg])
    with pytest.raises(SopsError) as info:
        dynaconf_sops.verify(settings)
    assert SECRET not in _all_text(info.value)


def test_debug_log_has_file_and_path_only(
    secrets: Path, write: Write, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = write(
        "s.yaml",
        f'LOADERS_FOR_DYNACONF: {LOADERS}\ndb:\n  password: "@sops app:db.password"\n'
        '  m: "@sops app:db.map"\n',
    )
    with caplog.at_level(logging.DEBUG):
        settings = Dynaconf(settings_files=[cfg])
        assert settings.db.password == SECRET
        assert settings.db.m == {"inner": SECRET}
    ours = [r for r in caplog.records if r.name.startswith("dynaconf_sops")]
    assert len(ours) == 2
    for record in ours:
        assert record.levelno == logging.DEBUG
        assert str(secrets) in record.getMessage()
    for record in caplog.records:
        assert SECRET not in record.getMessage()


def test_library_logs_nothing_above_debug(
    secrets: Path, write: Write, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    cfg = write("s.yaml", f'a: "@sops app:db.password"\nb: "@sops {tmp_path}/none.yaml#x"\n')
    settings = Dynaconf(settings_files=[cfg])
    with caplog.at_level(logging.DEBUG, logger="dynaconf_sops"):
        _ = settings.a
        with pytest.raises(SopsError):
            _ = settings.b
    assert all(r.levelno == logging.DEBUG for r in caplog.records)


def test_unresolved_repr_has_no_value(secrets: Path, write: Write) -> None:
    settings = Dynaconf(settings_files=[write("s.yaml", 'pw: "@sops app:db.password"\n')])
    raw = dict.__getitem__(settings.store, "PW")
    assert repr(raw) == "'@@sops app:db.password'"
    assert SECRET not in repr(raw)
    assert SECRET not in repr(dynaconf_sops.references(settings))


def test_no_files_written(secrets: Path, write: Write, tmp_path: Path) -> None:
    cfg = write("s.yaml", 'pw: "@sops app:db.password"\nm: "@sops app:db.map"\nw: "@sops app:"\n')
    settings = Dynaconf(settings_files=[cfg])
    before = _tree(tmp_path)
    assert settings.pw == SECRET
    assert settings.m == {"inner": SECRET}
    assert settings.w["num"] == 12345
    dynaconf_sops.verify(settings)
    assert _tree(tmp_path) == before
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.suffix != ".txt":  # age key files are .txt
            assert SECRET.encode() not in path.read_bytes() or path == secrets


def test_environment_passed_through(
    secrets: Path, write: Write, monkeypatch: pytest.MonkeyPatch, age_keys: AgeKeys
) -> None:
    # The key location comes only from the environment; sops must see it.
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(age_keys.key_file))
    settings = Dynaconf(settings_files=[write("s.yaml", 'db:\n  pw: "@sops app:db.password"\n')])
    assert settings.db.pw == SECRET
    dynaconf_sops.clear_cache()
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(age_keys.other_key_file))
    with pytest.raises(SopsError, match="exit code 128"):
        _ = settings.db.pw
