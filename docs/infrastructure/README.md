# Infrastructure Documents

This directory documents reusable platform infrastructure. Each subtree owns a bounded capability and exposes public contracts that downstream applications may compose without making a concrete application part of the platform.

- [`ai/`](ai/README.md) — model identity, assets, serving, prompts, qualification, and runtime asset management.
- [`environment/`](environment/README.md) ? downstream environment provider/session contract, conformance, reference provider, and project-facing evidence surfaces.
- [`minecraft/`](minecraft/README.md) — bundled reusable Minecraft environment provider, server/world runtime, action ABI, and qualification.
- [`runtime/`](runtime/README.md) — lifecycle, operator, service, release, endpoint, and execution control.
- [`server/`](server/README.md) — generic remote-host identity, connection, capacity, repository transport, and persistent-session control.
- [`observability/`](observability/README.md) — logs, telemetry, traces, diagnostics, and I/O/performance observation.
- [`ARTIFACT_CONTENT_MATERIALIZATION.md`](ARTIFACT_CONTENT_MATERIALIZATION.md) ? fail-closed archive extraction, owner-access normalization, digest verification, and atomic publication.

Reusable providers may be bundled upstream when they are independently useful across projects. Project-specific benchmark runtimes, task compositions, model selections, deployment fleets and scientific semantics remain downstream.
