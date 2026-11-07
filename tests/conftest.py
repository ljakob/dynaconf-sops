"""Shared fixtures: throwaway age keys and SOPS files created at runtime."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from dynaconf_sops._config import find_sops
from dynaconf_sops._errors import SopsError

ENV_VARS = (
    "DYNACONF_SOPS_DIR",
    "DYNACONF_SOPS_BIN",
    "DYNACONF_SOPS_TIMEOUT",
    "SOPS_AGE_KEY_FILE",
    "SOPS_AGE_KEY",
    "LOADERS_FOR_DYNACONF",
)


@dataclass(frozen=True)
class AgeKeys:
    key_file: Path
    recipient: str
    other_key_file: Path


def _keygen(path: Path) -> str:
    result = subprocess.run(
        ["age-keygen", "-o", str(path)], capture_output=True, text=True, check=True
    )
    for line in (result.stderr + path.read_text()).splitlines():
        if "age1" in line:
            return line[line.index("age1") :].split()[0]
    raise AssertionError("no recipient in age-keygen output")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    from dynaconf_sops import _cache

    _cache.clear_cache()
    yield
    _cache.clear_cache()


@pytest.fixture(scope="session")
def sops_bin() -> str:
    try:
        return find_sops()
    except SopsError:
        pytest.skip("sops binary not found; install sops to run these tests")


@pytest.fixture(scope="session")
def age_keys(tmp_path_factory: pytest.TempPathFactory) -> AgeKeys:
    if shutil.which("age-keygen") is None:
        pytest.skip("age-keygen not found; install age to run these tests")
    directory = tmp_path_factory.mktemp("age")
    key_file = directory / "key.txt"
    other = directory / "other.txt"
    recipient = _keygen(key_file)
    _keygen(other)
    return AgeKeys(key_file=key_file, recipient=recipient, other_key_file=other)


MakeSops = Callable[..., Path]


@pytest.fixture
def make_sops(
    sops_bin: str, age_keys: AgeKeys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> MakeSops:
    """Return ``make(name, content, directory=tmp_path)`` creating an encrypted file.

    The format follows the file extension. The plaintext is written to a
    separate scratch directory and removed right after encryption.
    """
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(age_keys.key_file))
    scratch = tmp_path / ".plain"

    def make(name: str, content: str, directory: Path | None = None) -> Path:
        target_dir = directory or tmp_path
        target_dir.mkdir(parents=True, exist_ok=True)
        scratch.mkdir(exist_ok=True)
        suffix = name.rsplit(".", 1)[-1]
        plain = scratch / f"plain.{suffix}"
        plain.write_text(content)
        target = target_dir / name
        try:
            subprocess.run(
                [
                    sops_bin,
                    "--encrypt",
                    "--age",
                    age_keys.recipient,
                    "--output",
                    str(target),
                    str(plain),
                ],
                capture_output=True,
                check=True,
                cwd=scratch,
                env={**os.environ, "SOPS_AGE_KEY_FILE": str(age_keys.key_file)},
            )
        finally:
            plain.unlink()
        return target

    return make


def write_stub(path: Path, body: str) -> Path:
    """Write an executable shell script used as a fake sops binary."""
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path
