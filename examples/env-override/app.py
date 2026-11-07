"""Environment variables: plain overrides win, references work in the environment too."""

from dynaconf import Dynaconf

settings = Dynaconf(settings_files=["settings.yaml"], envvar_prefix="APP")

print("database.user:", settings.database.user)  # APP_DATABASE__USER
print("database.password:", settings.database.password)  # from the file
print("cache.password:", settings.cache.password)  # APP_CACHE__PASSWORD (plain)
print("mail.password:", settings.mail.password)  # APP_MAIL__PASSWORD (a reference)
