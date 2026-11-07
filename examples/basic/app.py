"""Activation by import: ``import dynaconf_sops`` registers the @sops token."""

from dynaconf import Dynaconf

import dynaconf_sops  # noqa: F401  (must come before the settings are loaded)

settings = Dynaconf(settings_files=["settings.yaml"])

print("host:", settings.database.host)
print("user:", settings.database.user)
print("password:", settings.database.password)
print("port:", settings.database.port, type(settings.database.port).__name__)
