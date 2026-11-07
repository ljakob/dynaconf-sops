#!/usr/bin/env bash
# Loader activation from the settings file, JSON SOPS file.
source "$(dirname "$0")/../_lib.sh"

encrypt "$WORK/secrets/api.sops.json" <<'JSON'
{"api": {"token": "example-token", "scopes": ["read", "write"]}}
JSON

run_example
