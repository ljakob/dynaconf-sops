from __future__ import annotations

from pathlib import Path

import pytest

from dynaconf_sops._errors import SopsError
from dynaconf_sops._reference import build_expression, parse_reference


class TestFileForm:
    def test_absolute(self) -> None:
        ref = parse_reference("/etc/app/secrets.sops.yaml#db.password")
        assert ref.file == Path("/etc/app/secrets.sops.yaml")
        assert ref.path == "db.password"
        assert ref.expr == '["db"]["password"]'
        assert ref.text == "/etc/app/secrets.sops.yaml#db.password"

    def test_home_expanded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        ref = parse_reference("~/secrets/api.sops.yaml#api.token")
        assert ref.file == tmp_path / "secrets" / "api.sops.yaml"

    def test_relative_to_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        ref = parse_reference("conf/x.sops.json#a")
        assert ref.file == tmp_path / "conf" / "x.sops.json"

    def test_relative_to_sops_dir(self, tmp_path: Path) -> None:
        ref = parse_reference("x.sops.yaml#a", sops_dir=tmp_path)
        assert ref.file == tmp_path / "x.sops.yaml"

    def test_sops_dir_with_tilde(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        ref = parse_reference("x.sops.yaml#a", sops_dir="~/sops")
        assert ref.file == tmp_path / "sops" / "x.sops.yaml"

    def test_absolute_ignores_sops_dir(self, tmp_path: Path) -> None:
        ref = parse_reference("/abs/x.sops.yaml#a", sops_dir=tmp_path)
        assert ref.file == Path("/abs/x.sops.yaml")

    def test_normalized(self, tmp_path: Path) -> None:
        ref = parse_reference("../other/./x.sops.yaml#a", sops_dir=tmp_path / "dir")
        assert ref.file == tmp_path / "other" / "x.sops.yaml"

    def test_whitespace_stripped(self) -> None:
        ref = parse_reference("  /a/b.sops.yaml # key  ")
        assert ref.file == Path("/a/b.sops.yaml")
        assert ref.expr == '["key"]'

    def test_hash_in_bracket_path(self) -> None:
        ref = parse_reference('/a.sops.yaml#["we#ird"]')
        assert ref.expr == '["we#ird"]'

    def test_colon_in_file_form(self) -> None:
        ref = parse_reference("/a/b:c.sops.yaml#k")
        assert ref.file == Path("/a/b:c.sops.yaml")


class TestNameForm:
    def test_shorthand(self, tmp_path: Path) -> None:
        ref = parse_reference("mariadb:users.app.password", sops_dir=tmp_path)
        assert ref.file == tmp_path / "mariadb.sops.yaml"
        assert ref.expr == '["users"]["app"]["password"]'

    def test_without_sops_dir_uses_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert parse_reference("db:pw").file == tmp_path / "db.sops.yaml"

    @pytest.mark.parametrize("name", ["a", "A_b-c.d", "x1", "my.app"])
    def test_allowed_names(self, name: str, tmp_path: Path) -> None:
        ref = parse_reference(f"{name}:k", sops_dir=tmp_path)
        assert ref.file == tmp_path / f"{name}.sops.yaml"

    def test_empty_path_is_whole_document(self, tmp_path: Path) -> None:
        ref = parse_reference("mariadb:", sops_dir=tmp_path)
        assert ref.expr is None
        assert ref.path == ""


class TestPath:
    @pytest.mark.parametrize(
        ("path", "expr"),
        [
            ("a", '["a"]'),
            ("a.b", '["a"]["b"]'),
            ("users.0.pw", '["users"][0]["pw"]'),
            ("list.10", '["list"][10]'),
            ("007", "[7]"),
            ("a-b.c_d", '["a-b"]["c_d"]'),
            ("with space", '["with space"]'),
            ('["dot.key"]', '["dot.key"]'),
            ('["a"][0]["b.c"]', '["a"][0]["b.c"]'),
            ("", None),
        ],
    )
    def test_expression(self, path: str, expr: str | None) -> None:
        assert build_expression("t", path) == expr

    def test_non_ascii_digits_are_keys(self) -> None:
        digit = chr(0x0661)  # ARABIC-INDIC DIGIT ONE: isdigit() but not ASCII
        assert build_expression("t", digit) == f'["{digit}"]'


class TestInvalid:
    @pytest.mark.parametrize(
        ("text", "fragment"),
        [
            ("", "empty reference"),
            ("   ", "empty reference"),
            ("#a.b", "missing file"),
            ("justafile.yaml", "expected '<file>#<path>'"),
            ("bad name:x", "expected '<file>#<path>'"),
            ("/a.sops.yaml#a..b", "empty key"),
            ("/a.sops.yaml#.a", "empty key"),
            ("/a.sops.yaml#a.", "empty key"),
            ("/a.sops.yaml#a[0]", "'[...]' form"),
            ('/a.sops.yaml#a"b', "'[...]' form"),
            ('/a.sops.yaml#["a"', "must end with ']'"),
        ],
    )
    def test_errors(self, text: str, fragment: str) -> None:
        with pytest.raises(SopsError) as info:
            parse_reference(text)
        assert fragment in str(info.value)
        assert repr(text.strip()) in str(info.value)
        assert info.value.reference == text.strip()
        assert info.value.returncode is None
        assert isinstance(info.value, ValueError)
