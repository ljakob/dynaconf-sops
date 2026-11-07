# Contributing

Thanks for helping. Bug reports, documentation fixes and pull requests are
welcome.

## Setup

You need [uv](https://docs.astral.sh/uv/), [sops](https://github.com/getsops/sops)
and [age](https://github.com/FiloSottile/age) (`age-keygen`).

```bash
git clone https://github.com/ljakob/dynaconf-sops.git
cd dynaconf-sops
uv sync
```

## Checks

```bash
scripts/check.sh --quick   # format, lint, mypy --strict, tests + coverage, examples, scans
scripts/check.sh           # additionally build + twine check and the Python/Dynaconf matrix
```

Every commit must pass `scripts/check.sh`. Coverage of `src/` must stay at or
above 90 %. `scripts/matrix.sh` runs the suite against the lowest and latest
supported Dynaconf on Python 3.10, 3.13 and 3.14; it needs those Pythons
(`uv python install 3.10 3.13 3.14`).

## Rules

- **No real secrets.** Tests and examples create throwaway age keys at runtime
  (in `tmp_path` or a temporary directory). Never commit a private key; the
  secret scan in `check.sh` rejects `AGE-SECRET-KEY-...` and private key
  headers.
- Secret values must never reach command lines, exception messages, log
  output, `repr()` or files. Add a test to `tests/test_security.py` for any new
  code path that handles values.
- The runtime dependencies are the standard library and Dynaconf. Development
  tools go into the `dev` dependency group.
- Only ASCII in `src/`.
- Keep the public API (`dynaconf_sops.__all__`) small; internals live in
  `_`-prefixed modules.

## Commits and pull requests

- One logical change per commit, imperative subject line ("Add ...", "Fix
  ..."), body explaining why if it is not obvious.
- Update `CHANGELOG.md` (section `Unreleased`) and the docs for user-visible
  changes.
- Pull requests run the CI workflow; it must be green.
