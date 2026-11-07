# Reference

Public API of `dynaconf_sops` 0.1. Everything not listed here is internal.

## Package `dynaconf_sops`

Importing the package registers the `@sops` converter with Dynaconf
(`register()` without arguments).

### `register(*, sops_dir=None, sops_bin=None, timeout=None) -> None`

Register the `@sops` converter (once per process) and set configuration.
Arguments are keyword-only; an argument left as `None` keeps its previous
value. Explicit values win over the environment variables below.

| Argument | Type | Meaning |
|---|---|---|
| `sops_dir` | `str \| os.PathLike \| None` | base directory for relative files and `name:path` references; `~` is expanded |
| `sops_bin` | `str \| os.PathLike \| None` | path of the sops binary, or a command name looked up on `PATH` |
| `timeout` | `float \| None` | seconds for one sops call, must be greater than 0 |

### `SopsError(ValueError)`

Raised for every problem with a reference: parsing, missing file, sops
failure, timeout, missing binary, invalid configuration. Raised on access of
the value (or by `verify()`), never while the settings load. The message
contains the reference, the file, the sops exit code and at most the first
line of sops' stderr (200 characters); never a value.

| Attribute | Type | Meaning |
|---|---|---|
| `reference` | `str \| None` | the reference text after `@sops` |
| `file` | `pathlib.Path \| None` | absolute SOPS file, if known |
| `path` | `str \| None` | key path as written |
| `returncode` | `int \| None` | sops exit code, if sops ran |
| `errors` | `tuple[SopsError, ...]` | individual errors of an aggregated `verify()` error, else empty |

### `verify(settings) -> int`

Resolve every `@sops` reference in `settings` once and return their number.
Raises one `SopsError` listing all failures (`errors` holds them). A
`"@sops ..."` string that was never converted counts as a failure. Successful
values are cached.

### `references(settings) -> dict[str, str]`

Map each setting holding a reference to the reference text, without
decrypting: `{"DATABASE.password": "@sops mariadb:users.app.password"}`.
Top-level keys are upper case (as Dynaconf stores them), list items appear as
`[i]`, combined forms as `@sops @format ...`.

### `secret_values() -> frozenset[str]`

The non-empty strings decrypted so far in this process, including strings
inside decrypted maps and lists. Intended for log redaction filters.

### `clear_cache() -> None`

Forget all cached values and empty `secret_values()`.

### `__version__: str`

The installed distribution version.

## Module `dynaconf_sops.loader`

### `load(obj, env=None, silent=True, key=None, filename=None, validate=False) -> None`

Dynaconf loader entry point, used through `LOADERS_FOR_DYNACONF`. Registers
the converter and turns remaining `"@sops ..."` strings into lazy values.
Nested values are replaced in place, top-level values through `obj.set()`.
Nothing is decrypted.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DYNACONF_SOPS_DIR` | unset (current directory) | base directory for relative files and `name:path` |
| `DYNACONF_SOPS_BIN` | `sops` on `PATH`, then `~/.local/bin/sops`, `/usr/local/bin/sops`, `/usr/bin/sops` | sops binary (path or command name) |
| `DYNACONF_SOPS_TIMEOUT` | `30` | seconds per sops call |
| `LOADERS_FOR_DYNACONF` | Dynaconf default | Dynaconf's own setting; add `dynaconf_sops.loader` for zero-code activation |

They are read when a value is accessed. Everything else in the environment
(`SOPS_AGE_KEY_FILE`, `SOPS_AGE_KEY`, cloud credentials, ...) is passed to sops
unchanged.

## Reference syntax

```text
reference  := "@sops" " " [formatter " "] target
formatter  := "@format" | "@jinja" | "@get" | "@read_file"   (Dynaconf decides, see below)
target     := file "#" path | name ":" path
name       := [A-Za-z0-9_.-]+                 -> <sops dir>/<name>.sops.yaml
path       := ""                              -> whole document
            | segment ("." segment)*          -> ["seg"]..., all-digit segment -> [n]
            | "[" ... "]"                     -> passed verbatim to sops --extract
```

Segments must not be empty and must not contain `[`, `]` or `"`. Leading and
trailing whitespace around the reference, the file and the path is ignored.
Formatters: Dynaconf 3.3 supports `@format`, `@jinja`, `@read_file`, `@get`;
Dynaconf 3.2 only `@format` and `@jinja`.

## Types

The value keeps the type it has in the decrypted document:

| In the SOPS file | Python |
|---|---|
| string | `str`, exactly as stored (a trailing newline is kept only if it is part of the value) |
| integer | `int` |
| float | `float` |
| `true` / `false` | `bool` |
| `null` | `None` |
| map | `dict` (plain dict: `value["key"]`, no attribute access) |
| list | `list` |

Supported file formats: YAML and JSON (format from the extension, as sops
decides). dotenv and INI files work for their string values but are not
officially supported in 0.1.

Quirks inherited from sops' JSON encoding: a float with an integral value
(`1.0e+20`) comes back as `int`; YAML timestamps (`2024-01-02`) come back as
ISO strings; integers beyond 64 bit come back as `float`.

## How sops is called

```text
sops --decrypt --output-type yaml [--extract EXPR] FILE
```

with `shell=False`, stdin closed, the environment inherited and the configured
timeout. Only the binary, these flags, the extract expression and the file
path are on the command line. sops prints strings verbatim and every other
value through its output format; with YAML output a non-string always ends in
a newline. If the output ends in a newline, sops runs a second time with
`--output-type json`: identical output means a string that ends in a newline,
different output is parsed as JSON. The whole document (empty path) is
fetched with `--output-type json` and no `--extract`.

Common sops exit codes (sops 3.13): 1 key path not found or file not
encrypted, 2 path runs through a scalar, 91 invalid extract expression,
100 file not found, 128 no key could decrypt the data key.

## Dynaconf versions

| Behaviour | 3.2.2 - 3.2.x | 3.3.0 - 3.3.1 | 3.3.2 | 3.3.3 and later |
|---|---|---|---|---|
| core features, both activation modes | yes | yes | yes | yes |
| `@sops @get`, `@sops @read_file` | no | yes | yes | yes |
| strings like `"@sopsy"` load as plain strings | no (`KeyError`, Dynaconf bug) | no | yes | yes |
| a section merge (validators, `set`) evaluates the section's lazy values | yes | no | no | yes |
| top-level attribute cache (rotation needs `reload()`) | no | yes | yes | yes |

Dynaconf 3.2.0 and 3.2.1 are not supported: they decrypt top-level references
on `settings.reload()`.
