#!/usr/bin/env bash
# One shared SOPS file per service family, referenced as name:path.
source "$(dirname "$0")/../_lib.sh"

encrypt "$WORK/sops/mariadb.sops.yaml" <<'YAML'
users:
  news:
    password: news-password
  reporting:
    password: reporting-password
root_password: never-requested
YAML

export DYNACONF_SOPS_DIR="$WORK/sops"
run_example
