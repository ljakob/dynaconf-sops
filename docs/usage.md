# Usage guide

This guide covers activation, references, laziness, caching and the
interaction with Dynaconf features. The exact API is in
[reference.md](reference.md), the security model in [security.md](security.md)
and deployment patterns in [integration.md](integration.md).

## Activation

`"@sops ..."` strings are plain strings until something tells Dynaconf about
the token. There are two ways; both are idempotent and can be combined.

### Loader (zero code)

List `dynaconf_sops.loader` in `LOADERS_FOR_DYNACONF`. The list *replaces*
Dynaconf's default loaders, so keep `dynaconf.loaders.env_loader` in it, in
front of ours:

```yaml
# settings.yaml
LOADERS_FOR_DYNACONF: ["dynaconf.loaders.env_loader", "dynaconf_sops.loader"]
```

Where the setting can live:

| Place | Works |
|---|---|
| top level of a settings file | yes |
| under `default:` (or the active env) with `environments=True` | yes; the top level is ignored in that mode |
| environment variable `LOADERS_FOR_DYNACONF` (JSON list) | yes, with or without `envvar_prefix` |
| `<PREFIX>_LOADERS_FOR_DYNACONF`, `DYNACONF_LOADERS_FOR_DYNACONF` | **no**, Dynaconf ignores these |
| `Dynaconf(loaders=[...])` | yes |

Dynaconf runs these loaders after the settings files and after the env loader.
`dynaconf_sops.loader.load()` registers the converter and replaces every
remaining `"@sops ..."` string (from files and environment variables) by a lazy
value, without decrypting anything.

If the package is not installed, Dynaconf fails with `ModuleNotFoundError:
No module named 'dynaconf_sops'` when it sets up the settings.

### Import

```python
import dynaconf_sops  # registers the @sops converter
```

The import must happen **before** Dynaconf parses the settings (a `Dynaconf`
object is set up on first attribute access). If you need configuration in
code, call `dynaconf_sops.register(sops_dir=..., sops_bin=..., timeout=...)`.

### Which one?

Prefer the loader. With the import, file values are already lazy when the env
loader merges an override such as `APP_DATABASE__USER` into the `database`
section, and depending on the Dynaconf version that merge evaluates the other
lazy values of the section (see [Validators and merges](#validators-and-merges)).
The loader runs after the env loader, so this cannot happen while loading.

Once the package is imported (the loader imports it as well), the converter is
registered for the whole process: settings objects created later parse `@sops`
directly and behave like the import mode.

## References

```yaml
database:
  password: "@sops mariadb:users.app.password"        # <sops dir>/mariadb.sops.yaml
  replica: "@sops /etc/app/db.sops.yaml#replica.password"  # absolute
  token: "@sops ~/secrets/api.sops.yaml#api.token"      # home directory
  cert: "@sops tls.sops.yaml#server.cert"              # relative to the sops dir or cwd
  odd: '@sops app.sops.json#["key.with.dots"]["x"]'    # verbatim sops expression
  whole: "@sops mariadb:"                               # the whole document as a dict
```

- `<file>#<path>`: the first `#` separates file and path.
- `<name>:<path>`: `<sops dir>/<name>.sops.yaml`. Without `DYNACONF_SOPS_DIR`
  the current directory is used.
- Dotted path segments are keys; an all-digit segment is a list index.
- A path starting with `[` is handed to `sops --extract` verbatim; use it for
  keys containing `.`, `[`, `]` or `"`.
- Relative paths are resolved when the value is accessed, not when the settings
  load.

### Combined with Dynaconf formatters

The reference text itself can be computed by Dynaconf's lazy formatters:

```yaml
a: "@sops @format {env[HOME]}/secrets/api.sops.yaml#api.token"
b: "@sops @jinja {{ this.SECRETS_DIR }}/mariadb.sops.yaml#users.app.password"
c: "@sops @get SECRET_REF"            # Dynaconf >= 3.3
```

Dynaconf 3.2 only combines with `@format` and `@jinja` (`@jinja` needs
`jinja2`).

### From environment variables

```bash
export APP_DATABASE__PASSWORD='@sops mariadb:users.app.password'
```

works in both activation modes. A plain value in the environment overrides a
reference from a file as usual.

## When sops runs

Nothing is decrypted while the settings load. `sops` runs when a value is
accessed: `settings.database.password`, `settings.get("database.password")`,
`settings["database"]["password"]`. Each reference runs `sops` once or twice
(see [reference.md](reference.md#how-sops-is-called)); afterwards the value
comes from the cache.

Getting a section (`settings.database`) decrypts nothing; rendering it does:
`repr(settings.database)`, `print(settings.database)`, `settings.as_dict()`
and `dynaconf list` evaluate every reference they show. Keep secrets in
sections you do not dump.

## Caching and rotation

Decrypted values are cached per process. The cache key contains the file's
modification time and size, so a changed file (rotation, `git pull`) is
decrypted again on the next access, without a restart.
`dynaconf_sops.clear_cache()` empties the cache.

Dynaconf 3.3 has its own cache for **top-level attribute access**:
`settings.TOKEN` and `settings["TOKEN"]` keep the first value until
`settings.reload()` or a `settings.set()`. `settings.get("TOKEN")` and nested
keys (`settings.database.password`) are not affected. If you rely on rotation,
put references in sections or call `settings.reload()`.

## Validators and merges

Dynaconf merges a section whenever a dotted key in it is set. That happens for
`settings.set("database.user", ...)`, for validators on a key of the section
(they call `setdefault()`), and, in import mode, for environment overrides of a
sibling. Depending on the Dynaconf version (observed with 3.2.x and 3.3.3 or
later), the merge evaluates every lazy value of that section, which means
`sops` runs for those references at that moment. The library cannot prevent
this without patching Dynaconf. What is guaranteed:

- references outside the section are not touched;
- each reference is decrypted at most once (cache);
- validators on other sections or on top-level keys decrypt nothing.

So with `Validator("database.user", must_exist=True)` and
`database.password: "@sops ..."` the password is decrypted at validation time,
which fails on a machine without a key. Options: keep secrets in their own
section (`secrets.database_password`), or accept it and treat it like
`verify()`.

## Fail fast

```python
import dynaconf_sops

dynaconf_sops.verify(settings)  # decrypts every reference once
```

`verify()` raises one `SopsError` listing all failing references (its
`errors` attribute has the individual errors) and returns the number of
references. Use it at service start so a missing key is reported immediately
and not at the first request. It also reports `"@sops ..."` strings that were
never converted.

## Redacting logs

`dynaconf_sops.secret_values()` returns the non-empty strings decrypted so
far, including strings inside decrypted maps and lists:

```python
import logging

import dynaconf_sops


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in dynaconf_sops.secret_values():
            message = message.replace(secret, "***")
        record.msg, record.args = message, None
        return True
```

Attach the filter to your handlers. It only knows values that were decrypted
before the record is logged.

## Testing your application

- Use plaintext settings (or environment overrides) in tests; the package is
  inert when there are no references.
- To test code paths that decrypt, create a throwaway age key and SOPS file in
  a temporary directory (see `examples/*/run.sh`), or point
  `DYNACONF_SOPS_BIN` at a stub script.
- Call `dynaconf_sops.clear_cache()` between tests that rotate files.

## Troubleshooting

| Symptom | Cause |
|---|---|
| value is the literal string `"@sops ..."` | not activated: loader missing from `LOADERS_FOR_DYNACONF`, or `import dynaconf_sops` happened after the settings were loaded. `verify()` reports it. |
| `ModuleNotFoundError: No module named 'dynaconf_sops'` | the loader is listed but the package is not installed in this environment |
| `SopsError: ... sops binary not found` | install sops or set `DYNACONF_SOPS_BIN` |
| `SopsError: ... exit code 128: Failed to get the data key ...` | no key that can decrypt the file (`SOPS_AGE_KEY_FILE`, `~/.config/sops/age/keys.txt`, KMS credentials) |
| `SopsError: ... exit code 1: error truncating tree: component ['x'] not found` | the key path does not exist in the file |
| `KeyError: '@sopsfoo'` while loading (Dynaconf < 3.3.2) | Dynaconf bug: a string that starts with a registered token. Upgrade Dynaconf. |
| `sops` decrypts during `Dynaconf(..., validators=[...])` | see [Validators and merges](#validators-and-merges) |
| a settings file loads nothing, no error | Dynaconf skips files with an unknown suffix (`.yaml.new`, `.bak`, `.txt`); use `.yaml`/`.yml`/`.toml`/`.json` |
| sops runs while loading although nothing was accessed | import mode plus an env override of a sibling key; see [integration.md](integration.md#pitfalls) |
