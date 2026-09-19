# Security Policy

## Reporting a vulnerability

Please do not publish exploit details, sensitive logs, or proof-of-concept material in a public issue.

Use GitHub Private Vulnerability Reporting from the repository Security tab. This gives maintainers a private channel for triage and coordinated disclosure.

If the private reporting control is unavailable, open a minimal public issue stating only that you need a private security contact. Do not include vulnerability details in that issue.

## What to include privately

A useful report includes:

- the affected Noetrium version or exact commit;
- the affected subsystem and entry point;
- prerequisites and attack assumptions;
- deterministic reproduction steps when safe to provide;
- observed security impact;
- suggested mitigations, if known.

## Scope

Security-relevant examples include authorization or authority-boundary bypass, unsafe external effects, secret exposure, command execution, path traversal, artifact integrity failures, or recovery behavior that can falsely certify an uncertain result.

## Supported code

Noetrium is under active development. Security review is focused on the current default branch and current release line. Historical snapshots may no longer receive fixes unless a maintainer explicitly marks them supported.

## Coordinated disclosure

Please allow maintainers to investigate and prepare a fix before public disclosure. Maintainers may request additional reproduction evidence or propose a coordinated disclosure plan appropriate to the issue.

Security reports are evaluated against Noetrium's fail-closed design goals: uncertainty must not be silently promoted into trusted execution or trusted research evidence.

## Release security checks

Do not place credentials, private keys, access tokens, host secrets, private runtime profiles, or sensitive experiment evidence in issues, logs, release bundles, or example configuration.

Before release, run `python scripts/product_assurance_gate.py --full --output product-assurance.json` and the formal installed-artifact distribution qualification documented in `docs/release/DISTRIBUTION_QUALIFICATION.md`. Security fixes must preserve authority boundaries and fail-closed effect/evidence semantics.
