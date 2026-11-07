from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from dynaconf_sops import _cache
from dynaconf_sops._config import Config
from dynaconf_sops._errors import SopsError
from dynaconf_sops._reference import parse_reference

from .conftest import CountingSops, MakeSops, write_stub


@pytest.fixture
def counting(tmp_path: Path) -> tuple[Config, Path]:
    """A stub sops that logs each call and prints the content of VALUE_FILE."""
    log = tmp_path / "calls.log"
    value = tmp_path / "value.txt"
    value.write_text("v1")
    stub = write_stub(
        tmp_path / "sops",
        f'echo "$*" >> {log}\nsleep 0.05\ncat {value}',
    )
    return Config(sops_dir=None, sops_bin=str(stub), timeout=10), log


def _calls(log: Path) -> int:
    return len(log.read_text().splitlines()) if log.exists() else 0


def _target(tmp_path: Path, content: str = "a: 1\n") -> Path:
    target = tmp_path / "x.sops.yaml"
    target.write_text(content)
    return target


def test_one_call_per_reference(tmp_path: Path, counting: tuple[Config, Path]) -> None:
    cfg, log = counting
    target = _target(tmp_path)
    ref = parse_reference(f"{target}#a")
    assert _cache.lookup(ref, cfg) == "v1"
    assert _cache.lookup(ref, cfg) == "v1"
    assert _calls(log) == 1
    other = parse_reference(f"{target}#b")
    assert _cache.lookup(other, cfg) == "v1"
    assert _calls(log) == 2


def test_same_reference_different_spelling_shares_entry(
    tmp_path: Path, counting: tuple[Config, Path]
) -> None:
    cfg, log = counting
    target = _target(tmp_path)
    _cache.lookup(parse_reference(f"{target}#a.b"), cfg)
    _cache.lookup(parse_reference('x.sops.yaml#["a"]["b"]', sops_dir=tmp_path), cfg)
    assert _calls(log) == 1


def test_redecrypt_after_change(tmp_path: Path, counting: tuple[Config, Path]) -> None:
    cfg, log = counting
    target = _target(tmp_path)
    ref = parse_reference(f"{target}#a")
    assert _cache.lookup(ref, cfg) == "v1"
    (tmp_path / "value.txt").write_text("v2")
    target.write_text("a: 22\n")  # size changes
    assert _cache.lookup(ref, cfg) == "v2"
    assert _calls(log) == 2
    assert len(_cache._values) == 1  # stale entry dropped


def test_redecrypt_after_mtime_change(tmp_path: Path, counting: tuple[Config, Path]) -> None:
    cfg, log = counting
    target = _target(tmp_path)
    ref = parse_reference(f"{target}#a")
    _cache.lookup(ref, cfg)
    st = target.stat()
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    _cache.lookup(ref, cfg)
    assert _calls(log) == 2


def test_clear_cache(tmp_path: Path, counting: tuple[Config, Path]) -> None:
    cfg, log = counting
    ref = parse_reference(f"{_target(tmp_path)}#a")
    _cache.lookup(ref, cfg)
    assert _cache.secret_values() == {"v1"}
    _cache.clear_cache()
    assert _cache.secret_values() == frozenset()
    _cache.lookup(ref, cfg)
    assert _calls(log) == 2


def test_errors_are_not_cached(tmp_path: Path) -> None:
    flag = tmp_path / "ok"
    stub = write_stub(
        tmp_path / "sops", f"if [ -e {flag} ]; then printf fine; else echo boom >&2; exit 1; fi"
    )
    cfg = Config(sops_dir=None, sops_bin=str(stub), timeout=10)
    ref = parse_reference(f"{_target(tmp_path)}#a")
    with pytest.raises(SopsError, match="boom"):
        _cache.lookup(ref, cfg)
    flag.touch()
    assert _cache.lookup(ref, cfg) == "fine"


def test_missing_file_raises(tmp_path: Path, counting: tuple[Config, Path]) -> None:
    cfg, log = counting
    with pytest.raises(SopsError, match="not found"):
        _cache.lookup(parse_reference(f"{tmp_path}/none.sops.yaml#a"), cfg)
    assert _calls(log) == 0


def test_threads_single_call(tmp_path: Path, counting: tuple[Config, Path]) -> None:
    cfg, log = counting
    ref = parse_reference(f"{_target(tmp_path)}#a")
    barrier = threading.Barrier(8)
    results: list[object] = []

    def worker() -> None:
        barrier.wait()
        results.append(_cache.lookup(ref, cfg))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ["v1"] * 8
    assert _calls(log) == 1


def test_containers_are_copied(make_sops: MakeSops, sops_bin: str) -> None:
    target = make_sops("c.sops.yaml", "m:\n  user: u\n  pw: secret-pw\nl: [x, y]\n")
    cfg = Config(sops_dir=None, sops_bin=sops_bin, timeout=10)
    ref = parse_reference(f"{target}#m")
    first = _cache.lookup(ref, cfg)
    first["pw"] = "changed"
    assert _cache.lookup(ref, cfg)["pw"] == "secret-pw"
    assert _cache.secret_values() == {"u", "secret-pw"}
    _cache.lookup(parse_reference(f"{target}#l"), cfg)
    assert _cache.secret_values() == {"u", "secret-pw", "x", "y"}


def test_rotation_through_dynaconf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counting_sops: CountingSops
) -> None:
    """A changed SOPS file is picked up on the next access, without restart.

    Dynaconf 3.3 caches top-level *attribute* access (``settings.TOKEN``,
    ``settings["token"]``) until ``reload()``/``set()``; ``settings.get()`` and
    nested keys are re-evaluated. Documented in docs/usage.md.
    """
    from dynaconf import Dynaconf

    d = tmp_path / "sops"
    d.mkdir()
    secret = d / "m.sops.yaml"
    secret.write_text("v: 1\n")
    monkeypatch.setenv("DYNACONF_SOPS_DIR", str(d))
    cfg = tmp_path / "s.yaml"
    cfg.write_text('token: "@sops m:t"\ndb:\n  pw: "@sops m:pw"\n')
    settings = Dynaconf(settings_files=[cfg])
    assert settings.db.pw == 'value-["pw"]'
    assert settings.token == 'value-["t"]'
    assert len(counting_sops.calls()) == 2

    secret.write_text("v: 22\n")  # rotated: size changes
    assert settings.db.pw == 'value-["pw"]'
    assert settings.get("token") == 'value-["t"]'
    assert len(counting_sops.calls()) == 4  # both decrypted again
    _ = settings.token  # 3.3: Dynaconf's attribute cache; 3.2: our cache hit
    assert len(counting_sops.calls()) == 4


def test_dynaconf_33_caches_top_level_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dynaconf import Dynaconf

    from .conftest import DYNACONF_VERSION

    value = tmp_path / "value.txt"
    value.write_text("old")
    stub = write_stub(tmp_path / "sops", f"cat {value}")
    monkeypatch.setenv("DYNACONF_SOPS_BIN", str(stub))
    secret = _target(tmp_path)
    cfg = tmp_path / "s.yaml"
    cfg.write_text(f'token: "@sops {secret}#t"\n')
    settings = Dynaconf(settings_files=[cfg])
    assert settings.token == "old"
    value.write_text("new")
    secret.write_text("a: 22\n")
    assert settings.get("token") == "new"
    stale = DYNACONF_VERSION >= (3, 3, 0)
    assert settings.token == ("old" if stale else "new")
    settings.reload()
    assert settings.token == "new"
