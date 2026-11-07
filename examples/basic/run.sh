#!/usr/bin/env bash
# Import activation with an explicit, relative SOPS file.
source "$(dirname "$0")/../_lib.sh"

encrypt "$WORK/secrets/app.sops.yaml" <<'YAML'
database:
  password: example-password
  port: 5432
YAML

run_example
