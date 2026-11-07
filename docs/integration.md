# Integration patterns

How to wire dynaconf-sops into a service that runs on developer machines, in
CI and in production containers, with a worked example.

## The idea

One settings file in the repository serves every environment:

- on a **developer machine** it contains references, sops and a key are
  available, values are decrypted on access;
- in **production** the deployment renders the same settings as plaintext
  (no references), so the package does nothing and needs neither sops nor a
  key;
- in **CI** tests use plaintext values or environment overrides.

## Developer machine

Requirements: the `dynaconf-sops` package, a `sops` binary (on `PATH` or
`DYNACONF_SOPS_BIN`), a key that can decrypt the files (for age the default
`~/.config/sops/age/keys.txt` or `SOPS_AGE_KEY_FILE`) and, for `name:path`
references, `DYNACONF_SOPS_DIR` pointing at the directory with the SOPS files.

```bash
export DYNACONF_SOPS_DIR=~/infra/secrets
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt   # only if not the default
```

A `.envrc` (direnv) or the service's dev script is a good place for these.

## Production container (package inert)

The deployment renders plaintext settings, for example:

```yaml
# rendered settings, no references
LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]
freshrss:
  user: news_classifier
  password: the-rendered-password
```

- Keep `dynaconf-sops` installed in the image: the loader entry imports it and
  Dynaconf fails with `ModuleNotFoundError` if it is missing. Alternatively
  drop the loader entry when rendering.
- The loader finds no `"@sops ..."` strings and changes nothing; `verify()`
  returns `0`. Neither `sops` nor a key is needed.
- An accidental reference in rendered settings fails on access with
  `SopsError: sops binary not found`, a clear signal that rendering missed a
  value.

## CI

- Run tests with plaintext settings (a test settings file, or environment
  overrides such as `APP_FRESHRSS__PASSWORD=dummy`). A plain value in the
  environment replaces a reference from a file.
- With the loader, overriding a sibling key in a section (e.g.
  `APP_FRESHRSS__USER`) decrypts nothing at load. Accessing the reference
  itself would, so override every referenced key you use.
- If a job must decrypt real files, give it a dedicated key that can decrypt
  only what the job needs.

## Worked example: a news classifier service

The secrets live in a shared SOPS file `mariadb.sops.yaml` (before
encryption):

```yaml
users:
  news_classifier:
    user: news_classifier
    password: s3cr3t
  other_app:
    password: other
root_password: never-requested
```

The service's settings reference only its own password:

```yaml
# config.yaml
LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]
freshrss:
  user: news_classifier
  password: "@sops mariadb:users.news_classifier.password"
heisedata:
  url: https://example.org/feed
```

The code does not change; it uses Dynaconf as before. Two optional lines make
it robust:

```python
import logging

import dynaconf_sops
from dynaconf import Dynaconf

settings = Dynaconf(settings_files=["config.yaml"], envvar_prefix="NEWS")


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in dynaconf_sops.secret_values():
            message = message.replace(secret, "***")
        record.msg, record.args = message, None
        return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactSecrets())
    dynaconf_sops.verify(settings)  # fail fast if a key or file is missing
    connect(settings.freshrss.user, settings.freshrss.password)
```

What happens:

| Where | Setup | Result |
|---|---|---|
| developer machine | `DYNACONF_SOPS_DIR` points at the directory with `mariadb.sops.yaml`, age key present | `verify()` decrypts `users.news_classifier.password` once; `root_password` and the other users are never requested |
| container | rendered settings with `password: <plaintext>`, no sops, no key | works unchanged, `verify()` returns `0` |
| CI | `NEWS_FRESHRSS__PASSWORD=dummy` | the environment wins, nothing is decrypted |

Fallback if the settings file cannot carry the loader entry: set
`LOADERS_FOR_DYNACONF` in the environment, or add `import dynaconf_sops` at
the top of the module that creates the settings.

### Checklist for adopting it

1. Add `dynaconf-sops` to the service's dependencies.
2. Add the loader entry to the settings file (or `LOADERS_FOR_DYNACONF` in the
   environment, or one `import dynaconf_sops`).
3. Replace the secret in the settings by `"@sops <name>:<path>"`.
4. On developer machines set `DYNACONF_SOPS_DIR` (and `SOPS_AGE_KEY_FILE` if
   the key is not in the default place); make sure `sops` is on `PATH` or set
   `DYNACONF_SOPS_BIN`.
5. Keep the deployment rendering plaintext settings; keep the package in the
   image or drop the loader entry when rendering.
6. Optionally call `verify()` at start-up and add the redaction filter.
