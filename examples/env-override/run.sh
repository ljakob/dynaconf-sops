#!/usr/bin/env bash
# Environment overrides next to and instead of references.
source "$(dirname "$0")/../_lib.sh"

encrypt "$WORK/secrets/app.sops.yaml" <<'YAML'
database:
  password: db-password-from-sops
cache:
  password: never-used
mail:
  password: mail-password-from-sops
YAML

export APP_DATABASE__USER=user-from-env
export APP_CACHE__PASSWORD=plain-from-env
export APP_MAIL__PASSWORD='@sops secrets/app.sops.yaml#mail.password'
run_example
