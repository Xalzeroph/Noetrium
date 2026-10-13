# Noetrium Documentation

This directory contains the maintained documentation for the current public release line. Historical design notes, migration journals, machine-specific runbooks, experiment logs, and superseded architecture documents are intentionally not shipped on the default branch.

The source tree and executable tests are authoritative when prose and implementation disagree. Generated machine-readable indexes under `docs/architecture/` are source-derived artifacts and must be regenerated from the exact source cut they describe.

## Start here

- [`architecture/README.md`](architecture/README.md) — system architecture, authority model, execution semantics, recovery, and downstream boundaries.
- [`product/operator/UNIFIED_CLI.md`](product/operator/UNIFIED_CLI.md) — the supported `noetrium` command surface.
- [`infrastructure/README.md`](infrastructure/README.md) — deployment, runtime, resources, environments, and operational recovery.
- [`development/SINGLE_MAINLINE_WORKFLOW.md`](development/SINGLE_MAINLINE_WORKFLOW.md) — contribution workflow and validation expectations.
- [`governance/RELEASE_SYSTEM.md`](governance/RELEASE_SYSTEM.md) — release truth and release gates.
- [`release/DISTRIBUTION_QUALIFICATION.md`](release/DISTRIBUTION_QUALIFICATION.md) — wheel/sdist and installed-artifact qualification.

## Public boundary

The supported Python boundary is intentionally small:

```python
from noetrium import NoetriumUnit, run
```

`NoetriumUnit` carries immutable research semantics. `run` executes a unit root or a project through the platform runtime. Internal modules under `noetrium_platform` are implementation details unless a document explicitly states otherwise.

The supported command-line boundary is the single `noetrium` command. Use `noetrium --help` or `noetrium help <group>` for the exact command tree in the installed version.

## Documentation policy

Maintained documentation follows four rules:

1. Describe current behavior, not development history.
2. Use generic examples. Do not embed private projects, hostnames, local paths, credentials, experiment identifiers, or unpublished results.
3. Avoid duplicating version literals, generated topology, or test counts in prose when they can be read from authoritative metadata or generated evidence.
4. Delete superseded documents instead of keeping multiple conflicting descriptions on the release branch. Git history preserves historical rationale.
