"""Red probe for scripts/scan-secrets.sh: it must detect private key headers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scan-secrets.sh"

# Assembled at runtime so this file itself never contains a key header.
FAKE_AGE_KEY = "AGE-SECRET-" + "KEY-1" + "Q" * 58
FAKE_PEM_HEADER = "-----BEGIN " + "OPENSSH PRIVATE" + " KEY-----"


def _scan(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *map(str, paths)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("content", [FAKE_AGE_KEY, FAKE_PEM_HEADER])
def test_detects_private_key(tmp_path: Path, content: str) -> None:
    bad = tmp_path / "leak.txt"
    bad.write_text(f"some text\n{content}\nmore\n")
    result = _scan(bad)
    assert result.returncode == 1
    assert str(bad) in result.stdout


def test_clean_file_passes(tmp_path: Path) -> None:
    good = tmp_path / "ok.txt"
    good.write_text("age1qyqszqgpqyqszqgpqyqszqgpqyqszqgp public recipients are fine\n")
    result = _scan(good)
    assert result.returncode == 0, result.stderr


def test_script_does_not_match_itself() -> None:
    assert _scan(SCRIPT).returncode == 0
