# Security

What dynaconf-sops protects, what it does not, and how to deploy it safely.
To report a vulnerability see [SECURITY.md](../SECURITY.md).

## Threat model

dynaconf-sops moves decryption from "a decrypted copy on disk" to "the
running process asks sops for one value when it needs it". It does not add
cryptography; confidentiality rests on SOPS and the key you give it.

| Who | Can read | Notes |
|---|---|---|
| anyone with the repository | encrypted SOPS files, settings with references | references reveal file names and key paths, not values |
| a user who can read the key (`SOPS_AGE_KEY_FILE`, KMS credentials) | every value in files encrypted for that key | the library uses whatever key sops finds; it never narrows access |
| the process using the settings | the values it accesses | after access, values are ordinary Python objects in memory |
| other users on the host | the sops command line (`ps`, `/proc/*/cmdline`) | contains only flags, the extract expression and the file path, never a value |
| root / the same user | process memory, environment, key files | out of scope |

Out of scope: protecting values inside the process after access (memory
dumps, debuggers, `as_dict()`), and protecting the key itself.

## Guarantees (tested)

- **Command line**: `sops --decrypt --output-type yaml|json [--extract EXPR] FILE`
  with `shell=False`. No value is ever an argument.
- **No files**: values travel through a pipe from sops to Python. No temporary
  files, nothing written next to the settings.
- **Exceptions**: `SopsError` messages contain the reference, the file, the
  exit code and the first line of sops' stderr (truncated to 200 characters).
  Errors carry no exception context that could hold sops output.
- **Logging**: only `logging.getLogger("dynaconf_sops").debug(...)` with file
  and key path. Nothing at INFO or above.
- **Unresolved values**: `repr()` of a stored, not yet evaluated value shows
  `'@@sops <reference>'`.
- **Minimal decryption**: only the referenced value is extracted by sops; a
  reference to `users.app.password` never decrypts `root_password` into the
  process.
- **Laziness**: loading settings (files, environment, `reload()`) never runs
  sops when the loader is used and the package was not imported before the
  settings object was created. See the exceptions below.
- **Environment**: inherited unchanged, so sops' own key discovery applies.

## What dumps show

| Output | Before the value is accessed | After access |
|---|---|---|
| `repr()` of the raw stored value (`dynaconf inspect`, loader history) | `'@@sops <reference>'`, no value | the store keeps the lazy value, still `'@@sops <reference>'` |
| `dynaconf_sops.references(settings)` | reference text only, nothing is decrypted | same |
| `repr(settings.section)`, `print(settings.section)` | **evaluates**: decrypts the references of that section and shows the plaintext | plaintext |
| `settings.as_dict()`, `settings.to_dict()` | **evaluates every reference** and returns plaintext | plaintext |
| `dynaconf list` (CLI) | **evaluates every reference** and prints plaintext | plaintext |

The library controls only the first two rows. Dynaconf evaluates lazy values
whenever it renders a section or the whole configuration, so treat those
outputs as containing secrets. Do not log `settings.as_dict()` or a section,
and do not run `dynaconf list` where the output is recorded.

## When values are decrypted earlier than expected

Dynaconf, not this library, evaluates lazy values in these cases:

- rendering a section or everything (table above);
- merging a section: a validator on a key of that section, `settings.set()`
  of a dotted key in it, and in import mode an environment override of a
  sibling key (Dynaconf 3.2.x and 3.3.3 or later). All references of that
  section are decrypted, each at most once; other sections are untouched.

On a machine without a key this turns into a `SopsError` at that moment
instead of at first use. Keep secrets in a section of their own if you
validate or modify neighbouring keys.

## Caching and memory

- Decrypted values are cached per process, keyed by file, extract expression,
  modification time and size. A changed file is decrypted again on the next
  access; the old value stays in `secret_values()` until `clear_cache()`.
- Dynaconf 3.3 additionally caches top-level attribute access
  (`settings.TOKEN`) until `reload()`/`set()`.
- `clear_cache()` drops the library's references to the values; Python does
  not wipe memory, so copies may survive until garbage collection. Strings
  cannot be zeroed in Python.

## Rotation

Rotate a value by re-encrypting the SOPS file (`sops set`, `sops edit`,
`git pull`). Running processes pick up the new value on the next access of a
nested key or `settings.get()`; top-level attribute access needs
`settings.reload()` on Dynaconf 3.3. Old values may stay in memory as
described above; restart processes if that matters.

## The sops binary

The library runs the first `sops` it finds: `DYNACONF_SOPS_BIN`, then `PATH`,
then `~/.local/bin/sops`, `/usr/local/bin/sops`, `/usr/bin/sops`. Whoever can
put a `sops` earlier on `PATH` can receive decrypted values. On shared hosts
set `DYNACONF_SOPS_BIN` to an absolute path owned by root.

## Hosts and developer machines

The recommended split:

- **Developer machines** hold a personal key and use references directly; the
  settings file in the repository stays free of secrets.
- **Production hosts and containers** do not decrypt at runtime. The
  deployment renders plaintext settings (decrypting at deploy time with
  whatever process you trust), so the running service has neither the key nor
  `sops`. With no `@sops` in the rendered settings the library is inert; it
  can stay installed and listed in `LOADERS_FOR_DYNACONF`.
- **CI** uses plaintext test settings or environment overrides. If CI must
  decrypt, give it a dedicated key that can only read CI secrets.

See [integration.md](integration.md) for concrete setups.

## Recommendations

1. Use the loader (zero code) and call `dynaconf_sops.verify(settings)` at
   start-up, so failures surface early and in one place.
2. Add a logging filter based on `secret_values()`.
3. Never log `settings.as_dict()`, a whole section, or `dynaconf list` output.
4. Keep secrets in their own sections if validators touch neighbouring keys.
5. Pin `DYNACONF_SOPS_BIN` on shared hosts.
6. Encrypt each secret file only for the keys that need it (`.sops.yaml`
   creation rules); the library cannot do better than the key's reach.
