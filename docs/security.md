# Security notes

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

Decrypted values are cached per process (one sops call per reference) and
listed by `dynaconf_sops.secret_values()`, which you can use in a logging
filter to redact them.
