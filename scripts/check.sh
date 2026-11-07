#!/usr/bin/env bash
# Quality gate for dynaconf-sops. Run from anywhere inside the repository.
#
# Usage: scripts/check.sh [--quick]
#   --quick  skip the package build and the Python/Dynaconf version matrix
set -euo pipefail

quick=0
for arg in "$@"; do
    case "$arg" in
        --quick) quick=1 ;;
        -h | --help)
            sed -n '2,6p' "$0"
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

cd "$(git rev-parse --show-toplevel)"

results=()
failed=0

stage() {
    local name=$1
    shift
    echo "==> $name"
    if "$@"; then
        results+=("ok    $name")
    else
        results+=("FAIL  $name")
        failed=1
    fi
}

skip() {
    results+=("skip  $1")
}

ascii_only() {
    if grep -rnP '[^\x00-\x7F]' src; then
        echo "non-ASCII characters found in src/" >&2
        return 1
    fi
}

run_examples() {
    local found=0 script
    for script in examples/*/run.sh; do
        [[ -e "$script" ]] || continue
        found=1
        echo "--- $script"
        bash "$script" || return 1
    done
    [[ $found -eq 1 ]] || echo "(no examples yet)"
}

build_and_twine() {
    local out
    out=$(mktemp -d /tmp/dynaconf-sops-build.XXXXXX)
    # shellcheck disable=SC2064
    trap "rm -rf '$out'" RETURN
    uv build --quiet --out-dir "$out" && uvx --quiet twine check --strict "$out"/*
}

matrix() {
    if [[ -x scripts/matrix.sh ]]; then
        scripts/matrix.sh
    else
        echo "(no matrix yet)"
    fi
}

stage "ruff format" uv run --quiet ruff format --check .
stage "ruff check" uv run --quiet ruff check .
stage "mypy --strict" uv run --quiet mypy --strict src
stage "pytest + coverage" uv run --quiet pytest -q --cov --cov-report=term --cov-fail-under=90
stage "examples" run_examples
stage "secret scan" scripts/scan-secrets.sh
stage "ascii in src" ascii_only
if [[ $quick -eq 0 ]]; then
    stage "build + twine check" build_and_twine
    stage "version matrix" matrix
else
    skip "build + twine check"
    skip "version matrix"
fi

echo
echo "Summary:"
printf '  %s\n' "${results[@]}"
if [[ $failed -ne 0 ]]; then
    echo "check.sh: FAILED" >&2
    exit 1
fi
echo "check.sh: all green"
