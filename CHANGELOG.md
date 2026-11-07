# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-07

### Added

- `@sops` token for Dynaconf: `"@sops <file>#<path>"` and the shorthand
  `"@sops <name>:<path>"` for `<DYNACONF_SOPS_DIR>/<name>.sops.yaml`. Dotted
  paths with list indices, the whole document with an empty path, verbatim
  `[...]` sops expressions. The shorthand requires a sops dir; without one,
  or with a non-existent one, the error names `DYNACONF_SOPS_DIR` (or
  `register(sops_dir=...)`) instead of reporting a missing file.
- Lazy decryption: values are decrypted with `sops --decrypt --extract` on
  first access, never while the settings load.
- Zero-code activation with the loader `dynaconf_sops.loader` in
  `LOADERS_FOR_DYNACONF` (settings file or environment), and activation by
  `import dynaconf_sops`.
- Combination with Dynaconf's lazy formatters (`@sops @format ...`,
  `@sops @jinja ...`, on Dynaconf 3.3 also `@get` and `@read_file`) and
  references in environment variables.
- Values keep their type (`str`, `int`, `float`, `bool`, `None`, `dict`,
  `list`); strings are returned exactly as stored.
- Rotation-aware, thread-safe per-process cache (file, expression,
  modification time, size), `clear_cache()`.
- Configuration through `register(sops_dir=, sops_bin=, timeout=)` and
  `DYNACONF_SOPS_DIR`, `DYNACONF_SOPS_BIN`, `DYNACONF_SOPS_TIMEOUT`.
- `SopsError` with `reference`, `file`, `path`, `returncode`, `errors`;
  messages never contain values.
- Helpers `verify()` (fail fast), `check()` (failures by key, no raise),
  `references()` (no decryption) and `secret_values()`; the `TOKEN` constant
  (`"@sops"`).
- Documentation: usage guide, reference, security notes, integration patterns
  (including pitfalls found by the first consumer: env loader merges, TOML
  parsing of env values, silently skipped file suffixes, non-login shells);
  runnable examples.

[Unreleased]: https://github.com/ljakob/dynaconf-sops/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ljakob/dynaconf-sops/releases/tag/v0.1.0
