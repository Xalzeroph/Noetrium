# Unified Research OS downstream API and `noetrium` CLI

The downstream contract is intentionally singular.

- Python authoring/control API: `noetrium.api`
- Canonical owner: `noetrium_platform.product.api`
- Human/operator entrypoint: `noetrium`
- Lower Model, Environment, Participant, Method, Experimentation, Execution,
  Artifact, Evidence, Resource, Runtime, Reliability, and Portfolio APIs are
  internal platform authorities, not downstream SDK surfaces.

## Research OS boundary

Downstream research code describes scientific intent through:

- `ResearchProgram` / `ResearchProgramBuilder`
- `ResearchPortfolio`
- `ResearchDefinition` and automatically derived `ResearchImplementation`
- `ResearchNode`, `ResearchDependency`, typed inputs and outputs
- immutable `ResearchGraphRevision`, branches, tags, and revision diffs
- one `ResearchOS` control facade for run, inspect, pause, drain, interrupt,
  resume, retry, cancel, checkpoint, and reconcile

The product layer owns no domain truth. It composes lower authorities and
projects their capabilities through one stable research-facing model.

A downstream project must not assemble model serving, environment providers,
resource schedulers, experiment pools, checkpoint stores, evidence stores, or
recovery infrastructure. Those remain platform composition responsibilities.

## Authoring

A generated project separates user scientific semantics from platform shell.

`src/<package>/core.py` is the only generated file intended for scientific
editing. It exports one function:

```python
from noetrium.api import research_os as api


def build_research() -> api.ResearchPortfolio:
    # Arbitrary user-owned Python is allowed here.
    # Construct one program or hundreds; use any DAG and any supported/custom
    # semantics. The scaffold does not prescribe methods, benchmarks, metrics,
    # experiments, node kinds, or cross-program topology.
    return build_my_research_portfolio()
```

The only top-level contract is that `build_research()` returns a valid
`ResearchPortfolio` whose `portfolio_id` matches the project identity. The
implementation may use `ResearchProgramBuilder`, direct immutable Product
contracts, custom nodes, Machine-backed semantics, helper modules, generated
domain code, or any other Python organization that stays behind
`noetrium.api.research_os`.

The generated `src/<package>/research.py` shell calls `build_research()`,
checks only that top-level contract, and exposes `PORTFOLIO` plus `PROGRAMS`.
It owns no scientific topology and can be regenerated at any time.

Authors do not calculate implementation hashes. Named implementation callables
referenced from the returned Portfolio are frozen through canonical
ResearchImplementation identity. Runtime compilation adds dependency closure,
revision cut, environment/model/provider identity, execution evidence and
recovery state without requiring project code to assemble those systems.

## Project scaffold

`noetrium project create <project-id>` creates one semantics-neutral project
shape:

- `src/<package>/core.py` — user-owned scientific core;
- `src/<package>/research.py` — platform-owned generated Research OS shell;
- `project.manifest.json` — platform-managed project identity/provenance;
- `tests/test_generated_project.py` — generated top-level contract coverage.

There is no blueprint JSON, implementation-slot schema, provider template, or
fixed method/benchmark/metric/experiment skeleton. The default CUSTOM root in a
fresh `core.py` is only a structurally valid bootstrap and may be replaced
entirely.

`noetrium project sync --project .` regenerates only platform-owned shell/test
files. It does not parse, normalize, rewrite, or infer the scientific topology
inside `core.py`.

`noetrium project doctor --project .` verifies template/provenance identity,
deterministic platform shell, the public import boundary, and the single
core-to-ResearchPortfolio contract. It deliberately does not require specific
definition kinds, node kinds, benchmark structure, experiment structure, or DAG
shape beyond the canonical ResearchPortfolio invariants themselves.

`noetrium project test --project .` builds and installs the downstream package
in isolation before running its generated contract suite. Source-tree-only
success is not accepted.

## Revisions and live control

Scientific edits produce immutable research revisions rather than overwriting
accepted history.

```text
working definition
      |
      v
validate / compile
      |
      v
ResearchGraphRevision rN
      |
      +-- branch / tag / diff / merge
      |
      +-- run / inspect / pause / drain / interrupt
          resume / retry / cancel / checkpoint / reconcile
```

Execution history remains append-only. A future graph-diff/invalidation layer
uses revision identity to reuse unaffected completed work and mark only affected
descendants stale or invalidated.

Operational placement changes such as worker/GPU assignment must remain
separate from scientific identity. Scientific changes such as methods,
benchmarks, metrics, prompts, protocols, seeds, or environment semantics create
new research identity.

## Operator layer

The CLI/operator packages are internal product tooling beneath the Research OS.
Their legacy lifecycle facade and deterministic reference workload may remain
as implementation/conformance fixtures while migration is in progress, but
they are not exported by `noetrium.api` and are not a downstream extension
protocol.

Release qualification exercises the installed Research OS facade directly.
Wheel/sdist and exact-distribution container smoke checks use the internal
`ReferenceResearchOSPort` only as a deterministic conformance port.

## Failure and recovery principles

The unified surface must preserve lower-authority uncertainty rather than
inventing success:

- missing required bindings fail closed;
- an accepted revision is immutable;
- pause/drain/interrupt are explicit control operations;
- retries preserve logical operation identity;
- checkpoints accelerate recovery but do not replace journal truth;
- external-effect uncertainty is reconciled by the owning runtime/reliability
  authority;
- one paper/node failure does not invalidate unrelated portfolio branches;
- future live graph edits create a new revision and invalidate only the minimal
  affected subgraph.

The public API stays small even as lower platform capability grows. New lower
systems integrate upward into Research OS compilation/composition; they do not
create new downstream APIs.
