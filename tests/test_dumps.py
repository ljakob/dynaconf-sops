"""What dumps show before and after access (P3.3, see docs/security.md)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from dynaconf import Dynaconf

import dynaconf_sops

from .conftest import LOADERS, CountingSops

Write = Callable[[str, str], Path]

# `python -m dynaconf` needs 3.3; the console script entry point works everywhere.
CLI = "import sys; from dynaconf.cli import main; sys.argv[0] = 'dynaconf'; main()"

BODY = f"""\
LOADERS_FOR_DYNACONF: {LOADERS}
token: "@sops m:token"
db:
  user: u
  password: "@sops m:db.password"
"""


@pytest.fixture
def sops_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "sops"
    d.mkdir()
    (d / "m.sops.yaml").write_text("placeholder: true\n")
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(d))
    return d


def _raw(settings: Dynaconf, *keys: str) -> object:
    node: object = settings.store
    for key in keys:
        node = dict.__getitem__(node, key)  # type: ignore[arg-type]
    return node


def test_unresolved_repr_shows_reference(
    write: Write, sops_dir: Path, counting_sops: CountingSops
) -> None:
    settings = Dynaconf(settings_files=[write("s.yaml", BODY)])
    settings.get("db.user")
    lazy = _raw(settings, "DB", "password")
    assert repr(lazy) == "'@@sops m:db.password'"
    assert str(lazy) == "m:db.password"
    assert repr(_raw(settings, "TOKEN")) == "'@@sops m:token'"
    assert dynaconf_sops.references(settings)["DB.password"] == "@sops m:db.password"
    assert counting_sops.calls() == []


def test_resolved_value_is_in_dynaconf_dumps(
    write: Write, sops_dir: Path, counting_sops: CountingSops
) -> None:
    # Caveat (documented): Dynaconf evaluates lazy values for repr of a section,
    # as_dict() and to_dict(). The plaintext then appears in those outputs.
    settings = Dynaconf(settings_files=[write("s.yaml", BODY)])
    secret = 'value-["db"]["password"]'
    assert secret in repr(settings.db)
    assert settings.as_dict()["TOKEN"] == 'value-["token"]'
    assert settings.as_dict()["DB"]["password"] == secret
    assert len(counting_sops.calls()) == 2  # once per reference, then cached
    # the store keeps the Lazy: a rotated file is still picked up
    assert repr(_raw(settings, "DB", "password")) == "'@@sops m:db.password'"


def test_dynaconf_list_cli_decrypts(
    write: Write, sops_dir: Path, counting_sops: CountingSops, tmp_path: Path
) -> None:
    cfg = write("s.yaml", BODY)
    (tmp_path / "appconf.py").write_text(
        f"from dynaconf import Dynaconf\nsettings = Dynaconf(settings_files=[{str(cfg)!r}])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", CLI, "-i", "appconf.settings", "list"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert 'value-["db"]["password"]' in result.stdout
