# Round 17 — Unified Operator Control Plane

This round consolidates forensic, telemetry, recovery, release and architecture inspection into one machine-readable CLI.

Key changes:

1. Explicit-reference causal graph builder; temporal proximity never becomes a causal claim.
2. `why --graph`, `graph`, `crash-bundle`, `telemetry-query`, `telemetry-summary`, `recovery-state`, `release-verify`, `architecture-report` commands.
3. Telemetry reader uses SQLite `mode=ro` + `query_only=ON`; operator inspection cannot initialize or mutate telemetry state.
4. Durable recovery inspection is pure file reading and cannot create recovery directories/files.
5. Expected operator errors return structured JSON + nonzero exit. Programming defects are not swallowed.
