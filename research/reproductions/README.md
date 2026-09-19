# Research reproductions

Each reproduction package has exactly two handwritten declaration authorities:

- `source.py` — immutable source provenance (`ReproductionSourceRegistry`).
- `definition.py` — paper/catalog/lifecycle/claims and references to typed scientific assets (`ReproductionDefinition`).

Executable scientific facts do **not** belong in the reproduction declaration. They are owned by the typed subsystem that executes or evaluates them:

- benchmark cuts/tasks/splits → `research/benchmarks/*` + Study benchmark contracts;
- method fidelity → package `fidelity.py`;
- experiment design/model roles/budgets/measurements → `ResearchStudyDefinition`;
- method execution → UMM `MethodProgram` or the package's typed method assets;
- evidence/results → evidence and experimentation systems.

`reproduction.json` is generated and read-only. It is a projection for inspection, indexing and external tooling; editing it is never authoritative.


## Lifecycle authority

`ReproductionDefinition.lifecycle` is the only reproduction maturity/state authority. Catalog metadata does not carry a second status field. Global method catalogs project the exact package lifecycles as `reproduction_packages: [{package, lifecycle}]`; they never rank, collapse, or translate multiple package lifecycles into an aggregate status.

## Source semantics

A source candidate is discovery evidence only. A `MethodSourceLane` is classified immutable provenance and never enters Study identity. Executable implementation identity is project-owned through `ProjectMethodRequirement.implementation_digest`, verified against the bound participant implementation and propagated into the compiled research-plan/checkpoint identity. Paper-only, artifact-only, official, later-released, surrogate, and independent source lanes may coexist without changing this execution authority boundary.

## Catalog projection

Run:

```bash
python scripts/sync_reproductions.py
python scripts/sync_reproductions.py --check
```

The sync command loads only the restricted pure `definition.py` and `source.py` declarations, validates package asset/test references, regenerates package `reproduction.json` projections, and regenerates `research/catalog/reproduction_catalog.json`. It never mutates discovery scope or the final Research Program; `scripts/sync_research_program.py` is the only writer of `research_program.json`.

There is no legacy reproduction-schema reader or compatibility fallback.
