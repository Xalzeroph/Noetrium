# Status Documents

Status documents report development state for a particular reusable-platform source cut. They are projections, not topology, authority-classification, runtime, or scientific-result authorities.

Read [`../architecture/CURRENT_ARCHITECTURE_AUTHORITY.md`](../architecture/CURRENT_ARCHITECTURE_AUTHORITY.md) for documentation precedence. [`CURRENT_DEVELOPMENT_BASELINE.md`](CURRENT_DEVELOPMENT_BASELINE.md) records the latest maintained development baseline and known validation state; it does not override a newer normative architecture contract or generated source identity.

Current generated governance reports are:

- [`algorithm/ALGORITHM_REPORT.md`](algorithm/ALGORITHM_REPORT.md)
- [`concurrency/CONCURRENCY_REPORT.md`](concurrency/CONCURRENCY_REPORT.md)
- [`performance/PERFORMANCE_REPORT.md`](performance/PERFORMANCE_REPORT.md)

Each generated report is valid only for the exact source revision/digest it records. A later source change requires regeneration before the old report can be cited as current evidence.

Concrete downstream experiment execution, model selection, environment state, server inventory, and scientific result status are intentionally not tracked here. Those facts belong to the downstream repository that owns them.

Historical platform changes live under [`../history/`](../history/README.md). Historical release artifacts and historical validation counts never override validation of the current source tree.
