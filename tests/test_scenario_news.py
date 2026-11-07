"""Acceptance: the first real user, a news classifier service (P7.1).

Look-alike of the real setup: a shared ``mariadb.sops.yaml`` with several
users and a root password, settings that reference only the service's own
password, activation without code change (loader in the settings file) or
with one import, and the production container mode with rendered plaintext.
Each mode runs in a fresh interpreter, like the real service.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .conftest import MakeSops, write_stub

ROOT = Path(__file__).resolve().parents[1]

MARIADB = """\
users:
  news_classifier:
    user: news_classifier
    password: nc-Secret-123
  freshrss:
    user: freshrss
    password: frss-Secret-456
  backup:
    password: backup-Secret-789
root_password: ROOT-never-requested
"""

CONFIG = """\
LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]
freshrss:
  user: news_classifier
  password: "@sops mariadb:users.news_classifier.password"
heisedata:
  url: https://example.org/heise/feed
"""

RENDERED = """\
LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]
freshrss:
  user: news_classifier
  password: rendered-plaintext
heisedata:
  url: https://example.org/heise/feed
"""

# The service code: plain Dynaconf, no dynaconf_sops import.
APP = textwrap.dedent(
    """
    import logging, sys
    from dynaconf import Dynaconf

    settings = Dynaconf(settings_files=["config.yaml"], envvar_prefix="NEWS")
    print("url", settings.heisedata.url)
    print("user", settings.freshrss.user)
    print("password", settings.freshrss.password)
    """
)


@pytest.fixture
def service(make_sops: MakeSops, tmp_path: Path, sops_bin: str) -> dict[str, object]:
    """Service directory, infra SOPS directory and a recording sops wrapper."""
    infra = tmp_path / "infra" / "hosts" / "dockerhost" / "sops"
    make_sops("mariadb.sops.yaml", MARIADB, directory=infra)
    app_dir = tmp_path / "news_classifier"
    app_dir.mkdir()
    (app_dir / "config.yaml").write_text(CONFIG)
    log = tmp_path / "sops-args.log"
    wrapper = write_stub(tmp_path / "bin" / "sops", f'echo "$*" >> {log}\nexec {sops_bin} "$@"')
    env = {
        **os.environ,
        "DYNACONF_SOPS_DIR": str(infra),
        "DYNACONF_SOPS_BIN": str(wrapper),
    }
    return {"dir": app_dir, "env": env, "log": log}


def _run(code: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def _extracts(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [re.search(r"--extract (\S+)", line)[1] for line in log.read_text().splitlines()]  # type: ignore[index]


def _assert_only_own_password(log: Path) -> None:
    extracts = _extracts(log)
    assert extracts, "sops was never called"
    assert set(extracts) == {'["users"]["news_classifier"]["password"]'}


def test_loader_in_settings_file_no_code_change(service: dict[str, object]) -> None:
    result = _run(APP, service["dir"], service["env"])  # type: ignore[arg-type]
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "url https://example.org/heise/feed",
        "user news_classifier",
        "password nc-Secret-123",
    ]
    _assert_only_own_password(service["log"])  # type: ignore[arg-type]
    assert "ROOT" not in result.stdout + result.stderr


def test_loader_from_environment(service: dict[str, object]) -> None:
    app_dir: Path = service["dir"]  # type: ignore[assignment]
    (app_dir / "config.yaml").write_text(CONFIG.split("\n", 1)[1])  # no loader key
    env = {
        **service["env"],  # type: ignore[dict-item]
        "LOADERS_FOR_DYNACONF": '["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]',
    }
    result = _run(APP, app_dir, env)
    assert result.returncode == 0, result.stderr
    assert "password nc-Secret-123" in result.stdout


def test_import_fallback(service: dict[str, object]) -> None:
    app_dir: Path = service["dir"]  # type: ignore[assignment]
    (app_dir / "config.yaml").write_text(CONFIG.split("\n", 1)[1])
    result = _run("import dynaconf_sops\n" + APP, app_dir, service["env"])  # type: ignore[arg-type]
    assert result.returncode == 0, result.stderr
    assert "password nc-Secret-123" in result.stdout
    _assert_only_own_password(service["log"])  # type: ignore[arg-type]


def test_nothing_decrypted_until_access(service: dict[str, object]) -> None:
    code = textwrap.dedent(
        """
        from dynaconf import Dynaconf
        settings = Dynaconf(settings_files=["config.yaml"], envvar_prefix="NEWS")
        print(settings.heisedata.url, settings.freshrss.user)
        """
    )
    env = {**service["env"], "NEWS_FRESHRSS__USER": "override"}  # type: ignore[dict-item]
    result = _run(code, service["dir"], env)  # type: ignore[arg-type]
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://example.org/heise/feed override"
    assert _extracts(service["log"]) == []  # type: ignore[arg-type]


def test_integration_doc_example(service: dict[str, object]) -> None:
    """The worked example in docs/integration.md, run as-is."""
    doc = (ROOT / "docs" / "integration.md").read_text()
    blocks = re.findall(r"^```python\n(.*?)^```", doc, re.MULTILINE | re.DOTALL)
    assert len(blocks) == 1
    prelude = textwrap.dedent(
        """
        import logging as _logging

        def connect(user, password):
            _logging.getLogger("news").warning("connecting as %s with %s", user, password)
            print("connected", user, password == "nc-Secret-123")
        """
    )
    code = prelude + blocks[0] + "\nmain()\n"
    result = _run(code, service["dir"], service["env"])  # type: ignore[arg-type]
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "connected news_classifier True"
    assert "connecting as news_classifier with ***" in result.stderr  # redacted log line
    assert "nc-Secret-123" not in result.stderr
    _assert_only_own_password(service["log"])  # type: ignore[arg-type]


def test_verify_fails_fast_without_key(service: dict[str, object], tmp_path: Path) -> None:
    env = {**service["env"], "SOPS_AGE_KEY_FILE": str(tmp_path / "missing-key.txt")}  # type: ignore[dict-item]
    code = textwrap.dedent(
        """
        import dynaconf_sops
        from dynaconf import Dynaconf
        settings = Dynaconf(settings_files=["config.yaml"])
        try:
            dynaconf_sops.verify(settings)
        except dynaconf_sops.SopsError as exc:
            print(exc)
        """
    )
    result = _run(code, service["dir"], env)  # type: ignore[arg-type]
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("1 of 1 @sops reference(s) failed:")
    assert "FRESHRSS.password" in result.stdout
    assert "exit code 128" in result.stdout
    assert "nc-Secret" not in result.stdout


def test_container_mode_rendered_plaintext(service: dict[str, object], tmp_path: Path) -> None:
    """Production: rendered settings, no sops anywhere, no key, package inert."""
    app_dir: Path = service["dir"]  # type: ignore[assignment]
    (app_dir / "config.yaml").write_text(RENDERED)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    env = {
        k: v
        for k, v in service["env"].items()  # type: ignore[attr-defined]
        if k not in {"SOPS_AGE_KEY_FILE", "DYNACONF_SOPS_DIR"}
    }
    env["PATH"] = str(empty)
    env["DYNACONF_SOPS_BIN"] = str(tmp_path / "no-such-sops")  # any lookup would fail
    code = APP + "import dynaconf_sops\nprint('verified', dynaconf_sops.verify(settings))\n"
    result = _run(code, app_dir, env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-2:] == ["password rendered-plaintext", "verified 0"]
    assert _extracts(service["log"]) == []  # type: ignore[arg-type]
