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

A project authors the entire scientific program in one top-level module.

```python
from noetrium import api


def paper_method(payload=None):
    return payload


def benchmark():
    return ()


def primary_metric(value):
    return 0.0 if value is None else 1.0


builder = api.ResearchProgramBuilder("my-paper")
builder.method("method", implementation=paper_method)
builder.benchmark("benchmark", implementation=benchmark)
builder.metric("primary-metric", implementation=primary_metric)

builder.experiment(
    "main",
    definitions=("method", "benchmark"),
    outputs=(
        api.ResearchOutputSpec("trajectory", api.ResearchValueKind.ARTIFACT),
    ),
)
builder.evaluation(
    "evaluate",
    definitions=("primary-metric",),
    outputs=(
        api.ResearchOutputSpec("score", api.ResearchValueKind.METRIC),
    ),
)
builder.depends(
    "evaluate",
    "main",
    bindings=(
        api.ResearchInputBinding(
            "trajectory",
            "trajectory",
            api.ResearchValueKind.ARTIFACT,
        ),
    ),
)
builder.analysis("analysis", depends_on=("evaluate",))

PROGRAM = builder.freeze()
PORTFOLIO = api.ResearchPortfolio("my-paper", (PROGRAM,))
```

Authors do not calculate implementation hashes. A named module-scope callable
is converted into a `ResearchImplementation` automatically by freezing its
import-resolvable module/qualname and canonical callable-source digest. This
keeps authoring diffs fine-grained: changing an unrelated metric does not
invalidate a method. Runtime compilation adds the referenced dependency closure,
Git cut, environment, model, provider, and release provenance without changing
this authoring ergonomics.

## Project scaffold

`noetrium project create <project-id>` creates one project shape.

The generated scientific surface is:

- `src/<package>/research.py` — the complete ResearchProgram/Portfolio authoring
  module;
- `project.manifest.json` — platform-managed project identity/provenance;
- `tests/test_generated_project.py` — installed-package conformance coverage.

The scaffold deliberately does not generate `method.py`, `study.py`,
`application.py`, provider stubs, checkpoint plumbing, model bindings,
environment bindings, or resource configuration glue.

`noetrium project doctor --project .` verifies the template revision,
manifest/platform provenance, exact generated files, the downstream import
boundary, and the top-level ResearchProgram/ResearchPortfolio contract.

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
