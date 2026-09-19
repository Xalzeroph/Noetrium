# Research catalog

The catalog has one-way ownership. No generated artifact is also an authoring surface.

- `agent_reproduction_scope.json` is the exhaustive discovery authority. It is intentionally broader than active work and is never mutated by reproduction projection.
- `research_program_control.json` is the handwritten active-program control authority for policy, promoted platform gaps, innovation tracks, and project constraints.
- `benchmark_catalog.json` is generated only from `research/benchmarks/*/manifest.json`.
- `reproduction_catalog.json` is generated only from typed `research/reproductions/*/definition.py` and `source.py`.
- `research_program.json` is a read-only projection composed by `scripts/sync_research_program.py` from the control file plus the two generated catalogs.
- lineage `*_status.json` files are read-only projections over relationship-only lineage graphs and reproduction projections.

The active Research Program contains only methods with at least one typed reproduction package. Discovery-only papers remain in `agent_reproduction_scope.json` until they are promoted by creating a typed reproduction package.

Projection order:

```text
benchmark manifests ──> benchmark_catalog.json ──┐
typed reproductions ──> reproduction_catalog.json ├─> research_program.json
research_program_control.json ────────────────────┘

typed reproductions + lineage graphs ──> lineage status projections
```

Every arrow has exactly one writer. Deleting an authority input deletes its derived row on the next projection; stale upsert semantics are forbidden.

No catalog is a runtime service. External repositories remain references only. Method-specific science belongs to reproduction/downstream code; only reusable mechanisms justified by multiple real reproductions are promoted to platform systems.


## Peer-reviewed reproduction admission

Formal research pressure is publication-gated.

- `publication_quality_policy.json` defines eligible peer-reviewed venue classes and hard exclusions.
- `publication_registry.json` records verified method/benchmark publications and venue evidence.
- `peer_reviewed_discovery_sources.json` is the formal proceedings/journal discovery surface.
- `publication_priority_queue.json` is generated from publication, reproduction, benchmark and pressure projections.
- `pressure_suite.json` may contain only methods admitted by the publication registry.
- preprint-only, workshop-only, technical-report-only and unverified items do not consume formal pressure capacity.
- historical preprint reproductions may remain for engineering evidence, but they are not formal publication-priority lanes.

The formal lifecycle is:

```text
venue verification
→ lineage placement
→ native reproduction package
→ frozen benchmark adapter/cut
→ MethodProgram
→ Study / Experiment
→ measurements + baselines + ablations/statistics
→ immutable evidence
→ machine-checked pressure closure
→ hard-enforced regression lane
```
