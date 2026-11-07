# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

Only the latest release receives fixes.

## Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub's
[private vulnerability reporting](https://github.com/ljakob/dynaconf-sops/security/advisories/new)
("Report a vulnerability" on the Security tab). Do not open a public issue.

Include what you found, how to reproduce it, and the versions of
dynaconf-sops, Dynaconf, sops and Python. Do not include real secrets or keys;
a throwaway age key (`age-keygen`) is enough to reproduce any problem.

You can expect an acknowledgement within a week. Fixes are released as a new
patch version and announced in the changelog and a GitHub security advisory.

## Scope

In scope: values leaking through this library (command lines, exceptions,
logs, files, `repr()`), references decrypting more than they name, and
evaluation at load time contrary to the documentation.

Known limitations that are documented and not vulnerabilities: plaintext in
Dynaconf dumps after access (`as_dict()`, `dynaconf list`, `repr()` of a
section), decryption during Dynaconf section merges, and values remaining in
process memory. See [docs/security.md](docs/security.md).
