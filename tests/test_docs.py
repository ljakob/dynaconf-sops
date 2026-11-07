"""Documentation hygiene: links and anchors resolve, code blocks are valid."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from dynaconf import Dynaconf

ROOT = Path(__file__).resolve().parents[1]
GITHUB = "https://github.com/ljakob/dynaconf-sops/blob/main/"
DOCS = sorted((ROOT / "docs").glob("*.md"))
PAGES = [
    ROOT / n
    for n in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "RELEASING.md")
]
PAGES += DOCS
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BLOCK = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _anchors(page: Path) -> set[str]:
    text = BLOCK.sub("", page.read_text())
    return {_slug(m) for m in re.findall(r"^#+ (.+)$", text, re.MULTILINE)}


def _links(page: Path) -> list[str]:
    return LINK.findall(BLOCK.sub("", page.read_text()))


def _resolve(page: Path, target: str) -> tuple[Path, str] | None:
    if target.startswith(GITHUB):
        target = target.removeprefix(GITHUB)
        base = ROOT
    elif target.startswith(("http://", "https://", "mailto:")):
        return None
    else:
        base = page.parent
    path, _, anchor = target.partition("#")
    return (base / path if path else page).resolve(), anchor


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_links_resolve(page: Path) -> None:
    for target in _links(page):
        resolved = _resolve(page, target)
        if resolved is None:
            continue
        path, anchor = resolved
        assert path.exists(), f"{page.name}: broken link {target}"
        if anchor:
            assert anchor in _anchors(path), f"{page.name}: missing anchor {target}"


def test_docs_do_not_mention_working_files() -> None:
    for page in PAGES:
        text = page.read_text()
        assert "PLAN.md" not in text
        assert "PROMPT.md" not in text


@pytest.mark.parametrize("page", DOCS, ids=lambda p: p.name)
def test_python_blocks_compile(page: Path) -> None:
    for kind, code in BLOCK.findall(page.read_text()):
        if kind == "python":
            compile(code, f"{page.name}", "exec")


@pytest.mark.parametrize("page", DOCS, ids=lambda p: p.name)
def test_yaml_blocks_load(page: Path, tmp_path: Path) -> None:
    for i, (kind, code) in enumerate(BLOCK.findall(page.read_text())):
        if kind != "yaml":
            continue
        target = tmp_path / f"block{i}.yaml"
        target.write_text(code.replace("dynaconf_sops.loader", "dynaconf.loaders.env_loader"))
        settings = Dynaconf(settings_files=[target])
        assert dict.keys(settings.store), f"{page.name} block {i} loaded nothing"
