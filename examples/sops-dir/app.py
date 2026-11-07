"""Shorthand references with DYNACONF_SOPS_DIR, plus verify() and references()."""

from dynaconf import Dynaconf

import dynaconf_sops

settings = Dynaconf(settings_files=["settings.yaml"])

for key, reference in dynaconf_sops.references(settings).items():
    print(f"{key} -> {reference}")
print("verified:", dynaconf_sops.verify(settings))
print("freshrss.password:", settings.freshrss.password)
print("decrypted:", sorted(dynaconf_sops.secret_values()))
