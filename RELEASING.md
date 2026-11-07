# Releasing

Releases are published by GitHub Actions (`.github/workflows/release.yml`) when
a tag `v<version>` is pushed: build once, publish to TestPyPI, then to PyPI,
both through [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC, no API tokens), then attach the files to a GitHub release.

## One-time setup

1. **Accounts**: an account on [pypi.org](https://pypi.org) and one on
   [test.pypi.org](https://test.pypi.org) (separate accounts), both with
   two-factor authentication enabled.
2. **Pending publishers** (the project does not exist yet, so register a
   *pending* publisher; it reserves nothing until the first upload):
   - PyPI: *Your account → Publishing → Add a new pending publisher → GitHub*
   - TestPyPI: the same on test.pypi.org

   | Field | PyPI | TestPyPI |
   |---|---|---|
   | PyPI project name | `dynaconf-sops` | `dynaconf-sops` |
   | Owner | `ljakob` | `ljakob` |
   | Repository name | `dynaconf-sops` | `dynaconf-sops` |
   | Workflow name | `release.yml` | `release.yml` |
   | Environment name | `pypi` | `testpypi` |

   After the first successful upload the pending publisher becomes a normal
   publisher of the project.
3. **GitHub environments** (*Settings → Environments*): create `testpypi` and
   `pypi`. For `pypi` add yourself as *Required reviewer* so every PyPI upload
   waits for an approval. Optionally restrict both to tags `v*`
   (*Deployment branches and tags → Selected → Add rule → Tag `v*`*).
4. Recommended: *Settings → Code security → Private vulnerability reporting →
   Enable* (referenced by `SECURITY.md`), and a branch protection rule for
   `main` that requires the CI checks.

## Release steps

1. Make sure `main` is green in CI and locally:

   ```bash
   scripts/check.sh
   ```

2. Set the version in `pyproject.toml` (`version = "X.Y.Z"`).
3. In `CHANGELOG.md`, rename `## [Unreleased]` content into
   `## [X.Y.Z] - YYYY-MM-DD`, keep an empty `## [Unreleased]` above it, and
   update the compare links at the bottom. For 0.1.0 replace
   `- unreleased` by the date.
4. Commit: `git commit -am "Release X.Y.Z"` and push `main`; wait for CI.
5. Tag and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "dynaconf-sops X.Y.Z"
   git push origin vX.Y.Z
   ```

6. Watch the *Release* workflow. The `build` job fails early if the tag does
   not match `pyproject.toml` or the changelog has no section for the version.
7. After the TestPyPI job, check the TestPyPI release (below), then approve the
   `pypi` deployment in the workflow run.
8. Check <https://pypi.org/project/dynaconf-sops/> and the GitHub release.

## What to check on TestPyPI

- The project page renders the README (badges, tables, code blocks) and shows
  the right version, license (BSD-3-Clause), Python versions and URLs.
- Both files exist: `dynaconf_sops-X.Y.Z-py3-none-any.whl` and
  `dynaconf_sops-X.Y.Z.tar.gz`, with attestations.
- Installation works in a fresh environment (dependencies come from PyPI):

  ```bash
  uv venv /tmp/dsops-check && \
  uv pip install --python /tmp/dsops-check/bin/python \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    --index-strategy unsafe-best-match \
    "dynaconf-sops==X.Y.Z"
  PYTHON=/tmp/dsops-check/bin/python examples/sops-dir/run.sh
  ```

## Local rehearsal (before tagging)

```bash
out=$(mktemp -d /tmp/dynaconf-sops-rehearsal.XXXXXX)
uv build --out-dir "$out/dist"
uvx twine check --strict "$out"/dist/*
uv venv --python 3.12 "$out/venv"
uv pip install --python "$out/venv/bin/python" "$out"/dist/*.whl
for e in examples/*/run.sh; do PYTHON="$out/venv/bin/python" bash "$e"; done
```

## If something goes wrong

- **Failure before the PyPI job**: nothing is on PyPI. Fix on `main`, delete
  the tag (`git push origin :refs/tags/vX.Y.Z`, `git tag -d vX.Y.Z`) and tag
  again. TestPyPI does not accept the same file twice, so bump the patch
  version if the TestPyPI upload already happened.
- **A broken release on PyPI**: files cannot be replaced. *Yank* the release
  (PyPI → project → *Manage* → release → *Options → Yank*, give a reason) so
  installers skip it unless pinned exactly, then publish a fixed patch
  version. Delete a release only if it must disappear completely (e.g. it
  contains a secret); the version number can never be reused.
- **A secret was published**: rotate it first, then yank or delete.
