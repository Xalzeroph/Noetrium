# Governance Documents

This directory owns rules that protect the architecture and preserve
debuggability: gates, forensic evidence, failure diagnosis and the explicit
no-fallback/no-quality-degradation policy. These documents constrain platform
changes; they do not own scientific method behavior.

- [`DOCUMENTATION_CHANGE_POLICY.md`](DOCUMENTATION_CHANGE_POLICY.md) makes documentation part of every governed change and defines the upstream-source evidence rule for third-party provider changes.
- [`RELEASE_SYSTEM.md`](RELEASE_SYSTEM.md) defines the frozen release manifest/evidence/authority chain and the two-stage source/release boundary gate.
