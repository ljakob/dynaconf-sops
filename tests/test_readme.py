"""Every Python and YAML block in README.md runs against real sops (P5.1).

Shell blocks are illustrative (install, export, encrypt); the test applies the
exports itself and the examples in examples/*/run.sh run the same commands.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .conftest import MakeSops

README = Path(__file__).resolve().parents[1] / "README.md"
BLOCK = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _blocks(lang: str) -> list[str]:
    return [code for kind, code in BLOCK.findall(README.read_text()) if kind == lang]


def _block_starting(lang: str, first_line: str) -> str:
    matches = [b for b in _blocks(lang) if b.startswith(first_line)]
    assert len(matches) == 1, f"expected one {lang} block starting with {first_line!r}"
    return matches[0]


@pytest.fixture
def scenario(make_sops: MakeSops, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The quick-start layout: config.yaml, sops/mariadb.sops.yaml, ~/secrets/api.sops.yaml."""
    work = tmp_path / "work"
    home = tmp_path / "home"
    work.mkdir()
    (work / "config.yaml").write_text(_block_starting("yaml", "# config.yaml"))
    make_sops(
        "mariadb.sops.yaml",
        _block_starting("yaml", "# sops/mariadb.sops.yaml"),
        directory=work / "sops",
    )
    make_sops("api.sops.yaml", "api:\n  token: tok-1\n", directory=home / "secrets")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DYNACONF_SOPS_DIR", "./sops")  # as in the README
    monkeypatch.setenv("SECRETS_DIR", str(work / "sops"))
    monkeypatch.chdir(work)
    return work


def _run(code: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


QUICK_START = "from dynaconf import Dynaconf\n"


def test_option_a_loader_in_settings_file(scenario: Path) -> None:
    out = _run(_block_starting("python", QUICK_START), scenario)
    assert out.splitlines() == ["app", "change-me"]


def test_option_a_loader_from_environment(scenario: Path) -> None:
    config = scenario / "config.yaml"
    config.write_text(
        "\n".join(line for line in config.read_text().splitlines() if "LOADERS_FOR" not in line)
    )
    export = _block_starting("bash", "export LOADERS_FOR_DYNACONF=")
    value = export.split("=", 1)[1].strip().strip("'")
    out = _run(_block_starting("python", QUICK_START), scenario, {"LOADERS_FOR_DYNACONF": value})
    assert out.splitlines() == ["app", "change-me"]


def test_option_b_import(scenario: Path) -> None:
    _run(_block_starting("python", "import dynaconf_sops  # noqa"), scenario)


def test_top_example_explicit_file(scenario: Path) -> None:
    code = QUICK_START + textwrap.dedent(
        """
        settings = Dynaconf(settings_files=["config.yaml"])
        assert settings.database.token == "tok-1"
        """
    )
    _run(code, scenario)


def test_combined_formatters_block(scenario: Path) -> None:
    block = _block_starting("yaml", "api_key:")
    (scenario / "combo.yaml").write_text(
        "LOADERS_FOR_DYNACONF: "
        '["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]\n'
        f"secrets_dir: {scenario / 'sops'}\n" + block
    )
    code = QUICK_START + textwrap.dedent(
        """
        settings = Dynaconf(settings_files=["combo.yaml"])
        assert settings.api_key == "tok-1"
        assert settings.db_password == "change-me"
        """
    )
    _run(code, scenario)


def test_env_var_block(scenario: Path) -> None:
    export = _block_starting("bash", "export APP_DATABASE__PASSWORD=")
    name, value = export.removeprefix("export ").strip().split("=", 1)
    code = QUICK_START + textwrap.dedent(
        """
        settings = Dynaconf(settings_files=["config.yaml"], envvar_prefix="APP")
        assert settings.database.password == "change-me"
        """
    )
    (scenario / "config.yaml").write_text(
        'LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]\n'
        "database:\n  user: app\n"
    )
    _run(code, scenario, {name: value.strip("'")})


def test_helpers_block(scenario: Path) -> None:
    setup = QUICK_START + 'settings = Dynaconf(settings_files=["config.yaml"])\n'
    helpers = _block_starting("python", "import logging\n")
    check = textwrap.dedent(
        """
        refs = dynaconf_sops.references(settings)
        assert refs["DATABASE.password"] == "@sops mariadb:users.app.password"
        assert dynaconf_sops.secret_values() == {"change-me", "tok-1"}
        import io
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactSecrets())
        log = logging.getLogger("readme")
        log.addHandler(handler)
        log.warning("password is %s", settings.database.password)
        assert stream.getvalue() == "password is ***\\n", stream.getvalue()
        """
    )
    out = _run(setup + helpers + check, scenario)
    assert "DATABASE.password" in out


def test_all_python_and_yaml_blocks_are_covered() -> None:
    python = _blocks("python")
    yaml = _blocks("yaml")
    assert len(python) == 3
    assert len(yaml) == 3
    assert {b.splitlines()[0] for b in python} == {
        "from dynaconf import Dynaconf",
        "import dynaconf_sops  # noqa: F401  (registers @sops)",
        "import logging",
    }
