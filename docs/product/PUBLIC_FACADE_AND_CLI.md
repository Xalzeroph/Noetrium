# Unified downstream API and `noetrium` CLI

The common product boundary is intentionally small:

- Python contracts: `noetrium.api`; product composition: `noetrium.api`
- CLI: `noetrium`
- lifecycle intents: `run`, `inspect`, `stop`, `resume`, `reconcile`, `evidence`
- existing forensic tools: `research diagnose ...`
- existing management tools: `research manage ...`

`ResearchFacade` owns only product intent translation. It does not own run state, effect certainty, checkpoints, environment truth, model truth, or scientific success. A real application is injected through `ResearchApplicationPort` and must return a typed `ResearchResult` whose action and target match the request.

There is deliberately no ambient service locator and no implicit default production application.

## Python

```python
from noetrium.api import ResearchFacade

facade = ResearchFacade(my_application)
result = facade.inspect("run-123")
```

The request payload is recursively frozen at the facade boundary so callers cannot mutate an in-flight intent after dispatch.

## CLI project binding

Lifecycle commands resolve one downstream project. The project root defaults to
the current directory, and the target defaults to the project identity:

```bash
noetrium run
noetrium inspect
noetrium evidence
noetrium run run-123 --project ./my-project
noetrium run --project ./my-project --config ./runtime.json
```

If lifecycle execution is required, the project adds
`src/<package>/application.py` with
`build_application(config_path)`. The optional `--config` path is passed to
that project-owned factory. There is no module-factory CLI, ambient service
locator, or second application authority source.

The bundled `noetrium_platform.product.operator.reference` application exists
only as an internal qualification fixture. It is deterministic and checksummed,
but it is not a product entrypoint and it is **not** a substitute for
RunMachine/effect authority.

## Failure rules

- Missing application bindings fail closed.
- Result action/target drift is rejected.
- Corrupt reference state fails checksum verification.
- Decoded reference state is modeled as immutable typed `ReferenceState` / `ReferenceEvent` values; exact fields and lifecycle transitions are validated before any state is accepted or persisted.
- Real external-effect uncertainty must remain with the owning runtime/reliability authority; the product layer never converts missing evidence into success.

## Generic run-control binding

`bind_run_control_application(...)` translates product intents onto a typed `RunControlPort`. The adapter validates exact run identity, manifest digest, expected **RunMachine revision**, and resume checkpoint/cycle identity before dispatch. It does not persist run state, execute lifecycle effects itself, or infer external-effect certainty.

`RunControlReceipt` is a typed projection over the authoritative `RunMachine` cut. Lifecycle phase, control revision, checkpoint head, prepared-operation state, and accepted transition history come from the shared Machine Journal; RunControl itself owns no second phase/generation ledger. Failed or recovery-required state-changing receipts surface as `ResearchOperationFailure` carrying that Machine-backed projection.

## ROLE 03 run-control binding

`noetrium.api.bind_run_control_application(...)` is the canonical product adapter for `RunControlPort`. RunControl coordinates external lifecycle effects, reconciliation, checkpoint verification, and evidence, but the authoritative lifecycle state is the shared journal-backed `RunMachine`. Product code never persists a second run-state projection.

The binding requires one explicit `run_id`, its exact `run_manifest_digest`, and an injected `RunControlPort`. Payloads are exact and revision-fenced:

- `run`, `stop`, `reconcile`: `{"expected_revision": N}`
- `inspect`, `evidence`: no payload, or an optional `expected_revision`
- `resume`: `expected_revision`, `restore_checkpoint_id`, and an exact `restore_cycle_identity` object containing `run_id`, `decision_cycle_id`, `session_id`, `task_id`, and `trace_id`

The adapter rejects target, manifest, `MachineCut`, and evidence identity drift even when a downstream object is otherwise typed. A state-changing command that produces `failed` or `recovery_required`, or a `RunControlActionFailure`, raises `ResearchOperationFailure` carrying the authoritative Machine-backed `ResearchResult`. The CLI never rewrites uncertain external-effect state into success.

This closes the ROLE 06 consumer side of `CSR-06-GENERIC-RUN-LIFECYCLE-OPERATOR-HANDOFF-20260829`; final availability still depends on the ROLE 03 run-control implementation being present in the integrated source cut.

## Section 42 receipt-authority dependency

The product envelope must preserve producer-owned authority rather than invent semantics from a status string. `RunControlReceipt` carries the authoritative `MachineCut`, derives `control_revision` from that cut, and includes any pending prepared control operation plus checkpoint/evidence projections. There is no separate run-control event sequence or receipt-reference authority. The receipt still does not claim task or scientific validity; `ResearchResult` remains a product projection.

ROLE06 also waits for the ROLE01 PSC-03 neutral diagnostic metadata envelope instead of creating a competing diagnostic taxonomy.

## Downstream project experience

`noetrium project create <project-id>` creates one project shape in `./<project-id>` at version `0.1.0`. Destination and `--version` remain optional explicit overrides. There are no author/provider template profiles and no `--template` selector.

The generated project contains the canonical manifest plus only the common
scientific authoring surface:

- `method.py` with a compilable `AgentMethodSpec`;
- `study.py` with an `AgentStudySpec`;
- an installed-package conformance test.

Project identity exists only in `project.manifest.json`/package metadata; the
scaffold does not generate a duplicate `project.py`. It also does not generate
provider stubs, `research.py`, or a runtime application. All platform contracts
are imported through `noetrium.api`.

Provider/runtime/application code is an optional extension of the same project, not a second project type. If lifecycle execution is needed, the project adds `application.py` with `build_application(config_path)`; `noetrium run --project ... [--config ...]` loads it explicitly. A project without that optional module remains fully valid for method/study compilation and fails lifecycle execution with a clear "no runtime application" error.

`noetrium project doctor --project .` verifies the single template revision,
manifest identity/provenance, exact generated scientific files, the
`noetrium.api` import boundary, and typed Method/Study compilation.
`noetrium project test --project .` builds and installs the downstream package
into an isolated temporary site-packages before running its generated contract
suite. Source-tree-only success is not accepted.

## NPE reference authority

The historical `noetrium_platform.product.operator.reference` workload remains a narrow internal distribution smoke fixture only. It persists synthetic smoke state and therefore is **not** authoritative RunMachine lifecycle evidence.

Claim-grade NPE reference acceptance composes producer-owned contracts through a downstream-owned binding: the project supplies a typed ROLE03 `RunControlPort`, while the public ROLE06 adapter translates its receipts. The verifier exercises the public research compiler, the explicit binding seam, and the complete revision-fenced `run -> inspect -> stop -> resume -> reconcile -> evidence` lifecycle in separate fresh processes. The historical Operator smoke workload remains excluded.

The clean-room driver is deliberately materialized inside the generated downstream project and imports only `noetrium.api` and the Python standard library. It owns no Platform authority; it is a deterministic qualification binding whose state is stored at an explicit run-local path and reopened by a fresh process. Missing, malformed or non-finalized lifecycle receipts remain fail-closed.
