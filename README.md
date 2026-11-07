# dynaconf-sops

[![CI](https://github.com/ljakob/dynaconf-sops/actions/workflows/ci.yml/badge.svg)](https://github.com/ljakob/dynaconf-sops/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/dynaconf-sops)](https://pypi.org/project/dynaconf-sops/)
[![Python](https://img.shields.io/pypi/pyversions/dynaconf-sops)](https://pypi.org/project/dynaconf-sops/)

Lazy `@sops` token for [Dynaconf](https://www.dynaconf.com/): reference values
in [SOPS](https://getsops.io/)-encrypted files directly from your settings.

```yaml
# config.yaml
LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]
database:
  user: app
  password: "@sops mariadb:users.app.password"     # <sops dir>/mariadb.sops.yaml
  token: "@sops ~/secrets/api.sops.yaml#api.token"   # explicit file
```

## Why

- **Secrets stay encrypted** in your repository. The settings only say *where*
  a value lives; there is no decrypted copy on disk.
- **Lazy**: nothing is decrypted while Dynaconf loads. `sops` runs on first
  access of a value, once per process (rotation-aware cache).
- **Minimal exposure**: only the referenced value is decrypted
  (`sops --decrypt --extract`), never the whole file.
- **Zero code**: one loader entry in the settings file (or an environment
  variable) activates it. Alternatively `import dynaconf_sops`.
- **Inert without references**: rendered plaintext settings (for example in
  production containers) work unchanged, without `sops` or a key.
- **Any SOPS backend**: age, PGP, cloud KMS, Vault. The environment is passed
  to `sops`, so `SOPS_AGE_KEY_FILE` and friends just work.
- Small: standard library plus Dynaconf, fully typed.

## Install

```bash
pip install dynaconf-sops
```

You also need the [`sops`](https://github.com/getsops/sops/releases) binary and
a key that can decrypt your files (for age: `~/.config/sops/age/keys.txt` or
`SOPS_AGE_KEY_FILE`).

## Quick start

An encrypted file, e.g. `sops/mariadb.sops.yaml`, shown here before
`sops --encrypt --in-place`:

```yaml
# sops/mariadb.sops.yaml (plaintext before encryption)
users:
  app:
    password: change-me
root_password: never-requested
```

Point the library at the directory (or use explicit paths, see below):

```bash
export DYNACONF_SOPS_DIR=./sops
```

### Option A: zero code (recommended)

Add the loader to `LOADERS_FOR_DYNACONF` in the settings file as shown at the
top, and use Dynaconf as usual:

```python
from dynaconf import Dynaconf

settings = Dynaconf(settings_files=["config.yaml"])

print(settings.database.user)  # plain value, sops does not run
print(settings.database.password)  # sops runs now, once
```

Instead of the settings key you can set the environment variable (the list
replaces Dynaconf's default, so keep the env loader in it):

```bash
export LOADERS_FOR_DYNACONF='["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]'
```

With `environments=True`, put `LOADERS_FOR_DYNACONF` under `default:`;
Dynaconf ignores it at the top level of such a file.

### Option B: one import

Import the package **before** the settings are loaded; it registers the
`@sops` converter:

```python
import dynaconf_sops  # noqa: F401  (registers @sops)
from dynaconf import Dynaconf

settings = Dynaconf(settings_files=["config.yaml"])
assert settings.database.password == "change-me"
```

Both options can be combined and are idempotent. Prefer the loader: it runs
after the env loader, so an environment override of a key next to a reference
(`APP_DATABASE__USER=...`) decrypts nothing while loading. Once the package is
imported (the loader imports it too), later settings objects in the same
process see `@sops` at parse time and behave like option B.

## Reference syntax

| Reference | Meaning |
|---|---|
| `@sops <file>#<path>` | `file` is absolute, `~`-expanded, or relative to `DYNACONF_SOPS_DIR` (else the current directory) |
| `@sops <name>:<path>` | shorthand for `<DYNACONF_SOPS_DIR>/<name>.sops.yaml`; `name` is `[A-Za-z0-9_.-]+` |

| Path | sops `--extract` |
|---|---|
| `users.app.password` | `["users"]["app"]["password"]` |
| `users.0.name` (all-digit segment) | `["users"][0]["name"]` |
| *(empty)*, e.g. `mariadb:` | whole document |
| `["dotted.key"]["x"]` (starts with `[`) | passed verbatim, for keys containing `.` |

References combine with Dynaconf's lazy formatters and work in environment
variables:

```yaml
api_key: "@sops @format {env[HOME]}/secrets/api.sops.yaml#api.token"
db_password: "@sops @jinja {{ this.SECRETS_DIR }}/mariadb.sops.yaml#users.app.password"
```

```bash
export APP_DATABASE__PASSWORD='@sops mariadb:users.app.password'
```

## Configuration

| `register()` argument | Environment variable | Default |
|---|---|---|
| `sops_dir` | `DYNACONF_SOPS_DIR` | none: relative files are relative to the current directory |
| `sops_bin` | `DYNACONF_SOPS_BIN` | `sops` on `PATH`, then `~/.local/bin/sops`, `/usr/local/bin/sops`, `/usr/bin/sops` |
| `timeout` | `DYNACONF_SOPS_TIMEOUT` | `30` seconds per sops call |

Arguments of `dynaconf_sops.register(sops_dir=..., sops_bin=..., timeout=...)`
win over the environment; both are read at access time.

## Types

Values keep their type from the decrypted document: `str` (exactly as stored,
nothing stripped), `int`, `float`, `bool`, `None`, `dict` (a plain dict, use
`["key"]` access) and `list`. YAML and JSON SOPS files are supported. See
[docs/reference.md](https://github.com/ljakob/dynaconf-sops/blob/main/docs/reference.md#types)
for the few sops quirks.

## Errors

Every problem raises `dynaconf_sops.SopsError` (a `ValueError`) **on access**,
never while loading: invalid reference, missing file, missing key path, wrong
or missing key, missing `sops` binary, timeout. The message names the
reference, the file, the sops exit code and the first line of sops' error
output, never a value. Attributes: `reference`, `file`, `path`, `returncode`.

## Helpers

```python
import logging

import dynaconf_sops

# Fail fast at service start: decrypt every reference once, report all failures.
dynaconf_sops.verify(settings)

# Diagnostics without decrypting anything.
print(dynaconf_sops.references(settings))
# {'DATABASE.password': '@sops mariadb:users.app.password', ...}


# Redact decrypted values from log output.
class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in dynaconf_sops.secret_values():
            message = message.replace(secret, "***")
        record.msg, record.args = message, None
        return True


logging.getLogger().addFilter(RedactSecrets())
```

`dynaconf_sops.clear_cache()` forgets all decrypted values.

## Security in short

- Values never appear in `sops`' command line, in exception messages, in the
  library's log output (DEBUG only, file and path) or in temporary files.
- Unresolved values show the reference in `repr()`.
- **Caveat:** once accessed, a value is plain Python data. Dynaconf evaluates
  references when it renders a section or everything: `repr(settings.section)`,
  `settings.as_dict()` and `dynaconf list` show plaintext. Do not log them.
- Dynaconf validators on keys in a section that holds references may decrypt
  that section's references at validation time.

Details: [docs/security.md](https://github.com/ljakob/dynaconf-sops/blob/main/docs/security.md).

## Compatibility

| | Supported |
|---|---|
| Python | 3.10 to 3.14 |
| Dynaconf | 3.2.2 or later, below 4 (some combinations need 3.3, see the reference) |
| sops | 3.x on `PATH` or configured (tested with 3.13) |
| OS | Linux and macOS |

## Documentation

- [Usage guide](https://github.com/ljakob/dynaconf-sops/blob/main/docs/usage.md)
- [Reference](https://github.com/ljakob/dynaconf-sops/blob/main/docs/reference.md)
- [Security](https://github.com/ljakob/dynaconf-sops/blob/main/docs/security.md)
- [Integration patterns](https://github.com/ljakob/dynaconf-sops/blob/main/docs/integration.md)
- [Changelog](https://github.com/ljakob/dynaconf-sops/blob/main/CHANGELOG.md),
  [Contributing](https://github.com/ljakob/dynaconf-sops/blob/main/CONTRIBUTING.md),
  [Security policy](https://github.com/ljakob/dynaconf-sops/blob/main/SECURITY.md)

Not affiliated with the Dynaconf or SOPS projects.

## License

BSD-3-Clause, see [LICENSE](https://github.com/ljakob/dynaconf-sops/blob/main/LICENSE).
