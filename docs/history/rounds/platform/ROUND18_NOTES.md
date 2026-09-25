# Round 18 — Lifecycle / Health OS

- Dependency-solved component startup and reverse shutdown.
- Graph validation before side effects.
- Startup rollback that preserves rollback failures independently.
- Explicit lifecycle evidence for STARTING/READY/STOPPING/STOPPED/FAILED.
- Atomic per-component health records with process identity, heartbeat, progress and resource fields.
- Health monitor distinguishes READY, STARTING, STALLED, FAILED, STOPPED and UNKNOWN.
