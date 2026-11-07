# Examples

| Example | Shows |
|---|---|
| [basic](basic/) | activation with `import dynaconf_sops`, explicit relative file, typed value |
| [loader](loader/) | zero-code activation via `LOADERS_FOR_DYNACONF` in the settings file, JSON SOPS file, list value |
| [env-override](env-override/) | environment variables next to, instead of, and as references |
| [sops-dir](sops-dir/) | `name:path` shorthand with `DYNACONF_SOPS_DIR`, `references()`, `verify()`, `secret_values()` |

Each `run.sh` needs `sops` and `age-keygen`. It creates a throwaway age key and
the SOPS files in a temporary directory, runs `app.py` there, compares the
output with `expected.txt` and removes the directory. Set `PYTHON` to use an
interpreter other than the project's `uv` environment, e.g.
`PYTHON=/tmp/venv/bin/python ./run.sh`.

`scripts/check.sh` runs all of them.
