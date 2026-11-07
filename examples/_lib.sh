# Shared helpers for examples/*/run.sh (sourced, not executed).
#
# Every example runs in a fresh temporary directory with a throwaway age key.
# No key or plaintext secret is ever written into the repository.
set -euo pipefail

EXAMPLE_DIR=$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)
REPO_DIR=$(cd "$EXAMPLE_DIR/../.." && pwd)
# Python that has dynaconf-sops installed; override with PYTHON=/path/to/python.
PYTHON=${PYTHON:-"uv run --quiet --project $REPO_DIR python"}
SOPS=${SOPS:-$(command -v sops || echo "$HOME/.local/bin/sops")}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/dynaconf-sops-example.XXXXXX")
cleanup() {
    if [[ -n "${WORK:-}" && -d "$WORK" && "$WORK" == */dynaconf-sops-example.* ]]; then
        rm -rf -- "$WORK"
    fi
}
trap cleanup EXIT

# Create a throwaway age key in $WORK and export it for sops.
age-keygen -o "$WORK/key.txt" 2>/dev/null
AGE_RECIPIENT=$(grep -o 'age1[0-9a-z]*' "$WORK/key.txt" | head -1)
export SOPS_AGE_KEY_FILE="$WORK/key.txt"

# encrypt TARGET: read plaintext from stdin, write the encrypted file TARGET.
encrypt() {
    local target=$1
    mkdir -p "$(dirname "$target")"
    cat > "$target"
    "$SOPS" --encrypt --age "$AGE_RECIPIENT" --in-place "$target"
}

# Copy the example's files into $WORK, run app.py there, compare the output.
run_example() {
    cp "$EXAMPLE_DIR"/app.py "$EXAMPLE_DIR"/settings.yaml "$WORK"/
    local actual
    actual=$(cd "$WORK" && $PYTHON app.py)
    if ! diff -u "$EXAMPLE_DIR/expected.txt" <(printf '%s\n' "$actual"); then
        echo "example $(basename "$EXAMPLE_DIR"): output differs from expected.txt" >&2
        return 1
    fi
    printf '%s\n' "$actual"
}
