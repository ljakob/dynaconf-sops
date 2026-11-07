#!/usr/bin/env bash
# Scan files for private key material. Exit 1 if anything is found.
#
# Usage: scripts/scan-secrets.sh [PATH...]
# Without arguments, scans all files tracked by git (plus staged new files).
set -euo pipefail

# The patterns are written so that they do not match themselves.
patterns=(
    'AGE-SECRET-KEY-1[0-9A-Z]{20,}'
    '-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY( BLOCK)?-----'
)

if [[ $# -eq 0 ]]; then
    cd "$(git rev-parse --show-toplevel)"
    mapfile -d '' files < <(git ls-files -z --cached --others --exclude-standard)
else
    files=("$@")
fi

found=0
for pattern in "${patterns[@]}"; do
    if [[ ${#files[@]} -gt 0 ]] && grep -rIlE -e "$pattern" -- "${files[@]}" 2>/dev/null; then
        found=1
    fi
done

if [[ $found -ne 0 ]]; then
    echo "scan-secrets: private key material found in the files listed above" >&2
    exit 1
fi
