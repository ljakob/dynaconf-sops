from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from dynaconf_sops import _config
from dynaconf_sops._config import Config, Settings, find_sops
from dynaconf_sops._errors import SopsError
from dynaconf_sops._reference import parse_reference
from dynaconf_sops._runner import decrypt, first_line

from .conftest import AgeKeys, MakeSops, write_stub

DOC_YAML = """\
s: hello
s42: "42"
strue: "true"
snull: "null"
empty: ""
i: 42
neg: -7
f: 1.5
b: true
bf: false
n: null
ml: |
  line1
  line2
m:
  a: 1
  b: x
l: [1, two, {k: v}]
nested:
  users:
    - name: u0
      pw: p0
"dot.key": dotted
unicode: "gr\\u00fc\\u00df"
"""

DOC_JSON = (
    '{"s": "hello", "s42": "42", "i": 42, "f": 1.5, "b": true, "n": null,'
    ' "ml": "line1\\nline2\\n", "m": {"a": 1, "b": "x"}, "l": [1, "two", {"k": "v"}],'
    ' "nested": {"users": [{"name": "u0", "pw": "p0"}]}, "dot.key": "dotted"}'
)

EXPECTED: dict[str, Any] = {
    "s": "hello",
    "s42": "42",
    "strue": "true",
    "snull": "null",
    "empty": "",
    "i": 42,
    "neg": -7,
    "f": 1.5,
    "b": True,
    "bf": False,
    "n": None,
    "ml": "line1\nline2\n",
    "m": {"a": 1, "b": "x"},
    "l": [1, "two", {"k": "v"}],
    "nested.users.0.pw": "p0",
    "nested.users.0": {"name": "u0", "pw": "p0"},
    "l.2.k": "v",
    '["dot.key"]': "dotted",
    "unicode": "grüß",
}


def _config_for(sops_bin: str, timeout: float = 30.0) -> Config:
    return Config(sops_dir=None, sops_bin=sops_bin, timeout=timeout)


def _get(file: Path, path: str, sops_bin: str) -> Any:
    return decrypt(parse_reference(f"{file}#{path}"), _config_for(sops_bin))


@pytest.fixture
def yaml_file(make_sops: MakeSops) -> Path:
    return make_sops("data.sops.yaml", DOC_YAML)


@pytest.fixture
def json_file(make_sops: MakeSops) -> Path:
    return make_sops("data.sops.json", DOC_JSON)


@pytest.mark.parametrize(("path", "expected"), list(EXPECTED.items()))
def test_yaml_types(yaml_file: Path, sops_bin: str, path: str, expected: Any) -> None:
    value = _get(yaml_file, path, sops_bin)
    assert value == expected
    assert type(value) is type(expected)


@pytest.mark.parametrize(
    "path", ["s", "s42", "i", "f", "b", "n", "ml", "m", "l", "nested.users.0.pw", '["dot.key"]']
)
def test_json_types(json_file: Path, sops_bin: str, path: str) -> None:
    value = _get(json_file, path, sops_bin)
    assert value == EXPECTED[path]
    assert type(value) is type(EXPECTED[path])


def test_whole_document(yaml_file: Path, sops_bin: str) -> None:
    doc = _get(yaml_file, "", sops_bin)
    assert doc["s"] == "hello"
    assert doc["nested"]["users"][0]["pw"] == "p0"
    assert "sops" not in doc


def test_dotenv_string_values(make_sops: MakeSops, sops_bin: str) -> None:
    file = make_sops("app.sops.env", "A=1\nB=two\n")
    assert _get(file, "B", sops_bin) == "two"
    assert _get(file, "A", sops_bin) == "1"


class TestErrors:
    def test_missing_file(self, tmp_path: Path, sops_bin: str) -> None:
        with pytest.raises(SopsError, match="SOPS file not found") as info:
            _get(tmp_path / "nope.sops.yaml", "a", sops_bin)
        assert info.value.file == tmp_path / "nope.sops.yaml"
        assert info.value.returncode is None

    def test_missing_path(self, yaml_file: Path, sops_bin: str) -> None:
        with pytest.raises(SopsError) as info:
            _get(yaml_file, "nope.deeper", sops_bin)
        err = info.value
        assert err.returncode == 1
        assert err.path == "nope.deeper"
        assert err.reference == f"{yaml_file}#nope.deeper"
        assert "exit code 1" in str(err)
        assert "not found" in str(err)
        assert str(yaml_file) in str(err)

    def test_path_through_scalar(self, yaml_file: Path, sops_bin: str) -> None:
        with pytest.raises(SopsError) as info:
            _get(yaml_file, "s.x", sops_bin)
        assert info.value.returncode == 2
        assert "\n" not in str(info.value)
        assert "hello" not in str(info.value)

    def test_wrong_key(
        self, yaml_file: Path, sops_bin: str, age_keys: AgeKeys, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(age_keys.other_key_file))
        with pytest.raises(SopsError) as info:
            _get(yaml_file, "s", sops_bin)
        assert info.value.returncode == 128
        assert "data key" in str(info.value)

    def test_not_encrypted(self, tmp_path: Path, sops_bin: str) -> None:
        plain = tmp_path / "plain.yaml"
        plain.write_text("a: secretvalue\n")
        with pytest.raises(SopsError, match="metadata not found") as info:
            _get(plain, "a", sops_bin)
        assert "secretvalue" not in str(info.value)

    def test_missing_binary(self, yaml_file: Path, tmp_path: Path) -> None:
        cfg = Config(sops_dir=None, sops_bin=str(tmp_path / "no-sops"), timeout=5)
        with pytest.raises(SopsError, match="cannot run sops"):
            decrypt(parse_reference(f"{yaml_file}#s"), cfg)

    def test_timeout(self, tmp_path: Path) -> None:
        stub = write_stub(tmp_path / "slow-sops", "sleep 5")
        target = tmp_path / "x.sops.yaml"
        target.write_text("a: b\n")
        cfg = Config(sops_dir=None, sops_bin=str(stub), timeout=0.2)
        with pytest.raises(SopsError, match=r"timed out after 0\.2 s"):
            decrypt(parse_reference(f"{target}#a"), cfg)

    def test_invalid_utf8(self, tmp_path: Path) -> None:
        stub = write_stub(tmp_path / "sops", r"printf '\377\376'")
        target = tmp_path / "x.sops.yaml"
        target.write_text("a: b\n")
        with pytest.raises(SopsError, match="not valid UTF-8"):
            decrypt(parse_reference(f"{target}#a"), _config_for(str(stub)))

    def test_invalid_json(self, tmp_path: Path) -> None:
        stub = write_stub(tmp_path / "sops", "echo '{not json'")
        target = tmp_path / "x.sops.yaml"
        target.write_text("a: b\n")
        with pytest.raises(SopsError, match="not valid JSON"):
            decrypt(parse_reference(f"{target}#"), _config_for(str(stub)))

    def test_long_stderr_truncated(self, tmp_path: Path) -> None:
        stub = write_stub(tmp_path / "sops", f"echo '{'x' * 500}' >&2; echo second >&2; exit 3")
        target = tmp_path / "x.sops.yaml"
        target.write_text("a: b\n")
        with pytest.raises(SopsError) as info:
            decrypt(parse_reference(f"{target}#a"), _config_for(str(stub)))
        msg = str(info.value)
        assert "x" * 197 + "..." in msg
        assert "x" * 198 not in msg
        assert "second" not in msg
        assert info.value.returncode == 3


def test_first_line() -> None:
    assert first_line(b"\n\n  first \nsecond") == "first"
    assert first_line(b"") == "(no error message)"
    assert first_line(b"a\x1bb") == "a?b"


class TestDiscovery:
    def _exe(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_explicit_path(self, tmp_path: Path) -> None:
        exe = self._exe(tmp_path / "bin" / "my-sops")
        assert find_sops(exe) == str(exe)

    def test_explicit_name_on_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = self._exe(tmp_path / "bin" / "sops-3")
        monkeypatch.setenv("PATH", str(exe.parent))
        assert find_sops("sops-3") == str(exe)

    def test_explicit_missing(self, tmp_path: Path) -> None:
        with pytest.raises(SopsError, match="sops_bin argument"):
            find_sops(tmp_path / "missing")

    def test_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = self._exe(tmp_path / "env-sops")
        monkeypatch.setenv("DYNACONF_SOPS_BIN", str(exe))
        assert find_sops() == str(exe)

    def test_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DYNACONF_SOPS_BIN", "/nonexistent/sops")
        with pytest.raises(SopsError, match="DYNACONF_SOPS_BIN"):
            find_sops()

    def test_explicit_beats_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = self._exe(tmp_path / "a" / "sops")
        monkeypatch.setenv("DYNACONF_SOPS_BIN", "/nonexistent/sops")
        assert find_sops(str(exe)) == str(exe)

    def test_path_then_fallbacks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        on_path = self._exe(tmp_path / "path" / "sops")
        fb1 = tmp_path / "fb1" / "sops"
        fb2 = self._exe(tmp_path / "fb2" / "sops")
        monkeypatch.setattr(_config, "FALLBACK_BINARIES", (str(fb1), str(fb2)))
        monkeypatch.setenv("PATH", str(on_path.parent))
        assert find_sops() == str(on_path)
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        assert find_sops() == str(fb2)

    def test_home_fallback_expanded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = self._exe(tmp_path / ".local" / "bin" / "sops")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        monkeypatch.setattr(_config, "FALLBACK_BINARIES", ("~/.local/bin/sops",))
        assert find_sops() == str(exe)

    def test_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        monkeypatch.setattr(_config, "FALLBACK_BINARIES", (str(tmp_path / "nope"),))
        with pytest.raises(SopsError, match=r"sops binary not found.*DYNACONF_SOPS_BIN"):
            find_sops()


class TestSettings:
    def test_defaults(self, sops_bin: str) -> None:
        cfg = Settings().resolve()
        assert cfg.sops_dir is None
        assert cfg.timeout == 30.0
        assert cfg.sops_bin == sops_bin

    def test_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sops_bin: str) -> None:
        monkeypatch.setenv("DYNACONF_SOPS_DIR", str(tmp_path))
        monkeypatch.setenv("DYNACONF_SOPS_TIMEOUT", "2.5")
        cfg = Settings().resolve()
        assert cfg.sops_dir == tmp_path
        assert cfg.timeout == 2.5

    def test_explicit_beats_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sops_bin: str
    ) -> None:
        monkeypatch.setenv("DYNACONF_SOPS_DIR", "/elsewhere")
        monkeypatch.setenv("DYNACONF_SOPS_TIMEOUT", "bogus")
        cfg = Settings(sops_dir=tmp_path, timeout=3).resolve()
        assert cfg.sops_dir == tmp_path
        assert cfg.timeout == 3.0

    def test_dir_tilde(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert Settings(sops_dir="~/s").resolve_dir() == tmp_path / "s"

    @pytest.mark.parametrize("raw", ["abc", "0", "-1"])
    def test_bad_env_timeout(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("DYNACONF_SOPS_TIMEOUT", raw)
        with pytest.raises(SopsError, match="DYNACONF_SOPS_TIMEOUT"):
            Settings().resolve()

    def test_bad_explicit_timeout(self) -> None:
        with pytest.raises(SopsError, match="timeout argument"):
            Settings(timeout=0).resolve()


def test_environment_is_inherited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "env.txt"
    stub = write_stub(tmp_path / "sops", f'echo "$SOPS_AGE_KEY_FILE" > {out}; printf ok')
    target = tmp_path / "x.sops.yaml"
    target.write_text("a: b\n")
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", "/some/key.txt")
    assert decrypt(parse_reference(f"{target}#a"), _config_for(str(stub))) == "ok"
    assert out.read_text().strip() == "/some/key.txt"
    assert os.environ["SOPS_AGE_KEY_FILE"] == "/some/key.txt"
