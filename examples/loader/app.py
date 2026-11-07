"""Zero-code activation: no dynaconf_sops import, the settings file lists the loader."""

from dynaconf import Dynaconf

settings = Dynaconf(settings_files=["settings.yaml"])

print("url:", settings.api.url)
print("token:", settings.api.token)
print("scopes:", list(settings.api.scopes))
