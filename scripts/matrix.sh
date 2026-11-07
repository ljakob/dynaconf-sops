#!/usr/bin/env bash
# Run the test suite against the lowest and latest supported Dynaconf on the
# oldest and newest supported Python. Each run uses an isolated environment,
# the project .venv is not touched.
#
# Usage: scripts/matrix.sh [PYTHON...]   (default: 3.10 3.13 3.14)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

lowest=$(sed -n 's/.*"dynaconf>=\([0-9.]*\),.*/\1/p' pyproject.toml)
if [[ -z "$lowest" ]]; then
    echo "matrix: cannot read the Dynaconf lower bound from pyproject.toml" >&2
    exit 1
fi
pythons=("$@")
[[ ${#pythons[@]} -gt 0 ]] || pythons=(3.10 3.13 3.14)

failed=0
for py in "${pythons[@]}"; do
    for spec in "dynaconf==$lowest" "dynaconf<4"; do
        label="python $py, $spec"
        if out=$(uv run --quiet --isolated --python "$py" --with "$spec" \
            pytest -q -p no:cacheprovider 2>&1); then
            echo "ok    $label: $(tail -1 <<<"$out")"
        else
            echo "FAIL  $label"
            tail -30 <<<"$out"
            failed=1
        fi
    done
done
exit $failed
