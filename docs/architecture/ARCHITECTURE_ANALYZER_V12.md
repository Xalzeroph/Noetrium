# Architecture Analyzer — Current Capabilities

The analyzer validates both physical source structure and declared runtime/scientific authority. It is a release/debugging instrument, not merely a documentation generator.

## Report layers

1. **Physical Import Graph** — first-party dependencies with source path and line.
2. **Forbidden Boundary Rules** — API/implementation direction, scientific firewalls, composition-root constraints.
3. **Package Cycle Detection**.
4. **Declared Authority Audit** — component/state/side-effect/dataflow ownership.
5. **Source Invariants** — forbidden constructors, old façades, hidden path inference, raw exception rendering and other non-import constraints.
6. **Source Authority Audit** — single-writer/single-authority rules that cannot be expressed as package imports.
7. **Capability Graph** — source/declaration-derived providers and consumers.
8. **Operation Graph** — operation-type emission seams.
9. **Event Graph** — event producers/consumers, including dynamic families declared through `EMITTED_EVENT_TYPES` / `CONSUMED_EVENT_TYPES`.
10. **Structural Hotspots** — size/control-flow/import concentration.
11. **Optimization Risks** — I/O, lock, mutation, serialization and exception-boundary concentration.

The report includes a deterministic SHA-256 so an exact architecture state can be attached to release evidence.

## Current development report

```text
import_edges                  2095
import_violations             0
package_cycles                0
declared_authority_violations 0
source_invariant_violations   0
source_authority_violations   0
capability_graph_edges        6
operation_graph_edges         30
event_graph_edges             12
report_sha256                 86497956f3b5315fc2bfff3c4eb6672d6ade8074d078d69c0b78fde9926146e9
```

## Dynamic seam declarations

Helper-generated lifecycle events may not appear as literal `EventEnvelope(event_type=...)` calls. Their owning module declares the seam family directly in source:

```python
EMITTED_EVENT_TYPES = (...)
CONSUMED_EVENT_TYPES = (...)
```

The analyzer parses those declarations; there is no hand-maintained event graph file.

## Debugging/optimization use

Hotspot and optimization-risk scores prioritize inspection; they are not automatic refactor gates. High fan-in on stable API package roots is expected. I/O/lock/state-mutation concentration in mutable runtime/backends receives more scrutiny than a thin contract package with many consumers.
