"""The public API is exactly what the docs promise (P4.2)."""

from __future__ import annotations

import inspect

import dynaconf_sops
import dynaconf_sops.loader

PUBLIC = {
    "register",
    "SopsError",
    "verify",
    "secret_values",
    "references",
    "clear_cache",
    "__version__",
}


def test_all_is_exact() -> None:
    assert set(dynaconf_sops.__all__) == PUBLIC
    assert len(dynaconf_sops.__all__) == len(PUBLIC)


def test_public_names_have_docstrings() -> None:
    for name in PUBLIC - {"__version__"}:
        obj = getattr(dynaconf_sops, name)
        assert inspect.getdoc(obj), name
    assert inspect.getdoc(dynaconf_sops.loader.load)
    assert dynaconf_sops.__doc__
    assert dynaconf_sops.loader.__doc__


def test_no_other_public_attributes() -> None:
    public = {
        n
        for n in vars(dynaconf_sops)
        if not n.startswith("_") and not inspect.ismodule(getattr(dynaconf_sops, n))
    }
    assert public == PUBLIC - {"__version__"}
    submodules = {n for n in vars(dynaconf_sops) if inspect.ismodule(getattr(dynaconf_sops, n))}
    assert {m for m in submodules if not m.startswith("_")} <= {"loader"}


def test_loader_module_api() -> None:
    assert dynaconf_sops.loader.__all__ == ["load"]
    params = list(inspect.signature(dynaconf_sops.loader.load).parameters)
    assert params == ["obj", "env", "silent", "key", "filename", "validate"]


def test_register_is_keyword_only() -> None:
    sig = inspect.signature(dynaconf_sops.register)
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values())
    assert list(sig.parameters) == ["sops_dir", "sops_bin", "timeout"]


def test_sops_error_is_value_error() -> None:
    assert issubclass(dynaconf_sops.SopsError, ValueError)
    err = dynaconf_sops.SopsError("msg", reference="r", returncode=3)
    assert (err.reference, err.file, err.path, err.returncode, err.errors) == (
        "r",
        None,
        None,
        3,
        (),
    )


def test_py_typed_shipped() -> None:
    from importlib.resources import files

    assert files("dynaconf_sops").joinpath("py.typed").is_file()
