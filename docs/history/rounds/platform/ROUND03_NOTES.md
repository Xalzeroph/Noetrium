# Round 03 — Model Serving OS Deepening

Added:

- complete immutable `ModelStackSpec` digest;
- GPU fabric/NUMA-aware exact-size topology selection;
- role canary + throughput qualification evidence model;
- process identity reconciliation for PID reuse / stale supervisor detection;
- ordered recovery transaction that cannot skip steps;
- current open-model qualification matrix.

No runtime fallback was added. Placement or qualification failure stops the launch plan instead of changing model quality.
