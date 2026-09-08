# Public facade and `research` CLI

The common product boundary is intentionally small:

- Python contracts: `noetrium.contracts`; product composition: `noetrium.platform`
- CLI: `research`
- lifecycle intents: `run`, `inspect`, `stop`, `resume`, `reconcile`, `evidence`
- existing forensic tools: `research diagnose ...`
- existing management tools: `research manage ...`

`ResearchFacade` owns only product intent translation. It does not own run state, effect certainty, checkpoints, environment truth, model truth, or scientific success. A real application is injected through `ResearchApplicationPort` and must return a typed `ResearchResult` whose action and target match the request.

There is deliberately no ambient service locator and no implicit default production application.

## Python

```python
from noetrium.platform import ResearchFacade

facade = ResearchFacade(my_application)
result = facade.inspect("run-123")
```

The request payload is recursively frozen at the facade boundary so callers cannot mutate an in-flight intent after dispatch.

## CLI application binding

Lifecycle commands require an explicit application factory:

```bash
noetrium --application my_project.operator:build_application run run-123
noetrium --application my_project.operator:build_application inspect run-123
noetrium --application my_project.operator:build_application evidence run-123
```

Factories receive the optional `--application-config` path. Downstream projects use that hook to compose their own ROLE 03/04/05 bindings without exposing internal topology to users.

The bundled `noetrium_platform.product.operator.reference` application exists only to qualify the facade, persistence and installed distribution lifecycle. It is deterministic and checksummed, but it is **not** a substitute for a production run/effect authority and its `reconcile` action does not certify external effect certainty.

## Failure rules

- Missing application bindings fail closed.
- Result action/target drift is rejected.
- Corrupt reference state fails checksum verification.
- Decoded reference state is modeled as immutable typed `ReferenceState` / `ReferenceEvent` values; exact fields and lifecycle transitions are validated before any state is accepted or persisted.
- Real external-effect uncertainty must remain with the owning runtime/reliability authority; the product layer never converts missing evidence into success.

## Generic run-control binding

`bind_run_control_application(...)` is the typed platform adapter from the product facade to ROLE03 `RunControlPort`. The adapter validates exact run identity, manifest digest, expected generation and resume checkpoint/cycle identity before dispatch. It does not persist run state, execute lifecycle effects itself, or infer external-effect certainty.

ROLE03 `RunControlReceipt` remains authoritative. Failed or recovery-required state-changing receipts surface as `ResearchOperationFailure` carrying the typed `ResearchResult`; the CLI emits that authoritative result and exits non-zero instead of flattening uncertainty into success.

This closes `CSR-06-GENERIC-RUN-LIFECYCLE-OPERATOR-HANDOFF-20260829`: ROLE06 owns product-intent translation only, ROLE03 owns durable lifecycle truth, and ROLE02 owns adjacent effect/reconciliation certainty.

## ROLE 03 run-control binding

`noetrium.platform.bind_run_control_application(...)` is the canonical ROLE 06 adapter for the ROLE 03 `RunControlPort`. The adapter is a translation boundary only: ROLE 03 remains the authority for run identity, manifest identity, lifecycle phase, checkpoint identity, reconciliation and evidence. ROLE 06 does not persist a second run-state projection.

The binding requires one explicit `run_id`, its exact `run_manifest_digest`, and an injected `RunControlPort`. Payloads are intentionally exact and generation-fenced:

- `run`, `stop`, `reconcile`: `{"expected_generation": N}`
- `inspect`, `evidence`: no payload, or an optional `expected_generation`
- `resume`: `expected_generation`, `restore_checkpoint_id`, and an exact `restore_cycle_identity` object containing `run_id`, `decision_cycle_id`, `session_id`, `task_id`, and `trace_id`

The adapter rejects target, manifest, control-event-action, and evidence identity drift even if a downstream object is otherwise typed. A state-changing command that produces `failed` or `recovery_required`, or a ROLE 03 `RunControlActionFailure`, raises `ResearchOperationFailure` carrying the authoritative `ResearchResult`. The CLI serializes that result to stderr and exits with code `3`; it never rewrites an uncertain/recovery-required outcome into success.

This closes the ROLE 06 consumer side of `CSR-06-GENERIC-RUN-LIFECYCLE-OPERATOR-HANDOFF-20260829`; final availability still depends on the ROLE 03 run-control implementation being present in the integrated source cut.

## Section 42 receipt-authority dependency

The common product envelope must preserve producer-owned receipt contract identity/version and an immutable receipt/content reference; ROLE06 must not invent those semantics from a status string. ROLE03 `RunControlReceipt` now exposes the typed schema version `run-control.receipt.v1`, a complete `receipt_digest`, and a stable `RunControlReceiptReference` bound to the authoritative event sequence. The receipt still does not claim task or scientific validity. ROLE05 can consume the producer-owned `RunControlResearchResultSource` for Run/Evidence reads; `ResearchResult` remains a product projection until the remaining Trial/Task/Measurement sources are available and the unified read composition is wired.

ROLE06 also waits for the ROLE01 PSC-03 neutral diagnostic metadata envelope instead of creating a competing diagnostic taxonomy.

## Downstream project experience

`noetrium project create <project-id> <destination> --version <version>` now defaults to the Section-40/41 **author-first Level-0** profile. It binds canonical Portfolio `ProjectManifest` identity/provenance and generates paper-author modules (`methods.py`, `tasks.py`, `measurements.py`, `studies.py`) plus a public `research.py` Method Host entry point and public-boundary structural tests. It does **not** generate Participant/Model/Environment provider implementations, direct `RunControlPort` wiring, checkpoint stores, resource leases or evidence publishers.

Provider authors explicitly opt in with `--template provider`. That advanced template retains the public Participant/Model/Environment requirement/provider stubs and application binding seam and deliberately fails closed until real bindings are supplied. Provider-specific plumbing is therefore no longer the default New Project Experience.

`noetrium project test --project .` first builds and installs the generated downstream package into an isolated temporary `site-packages`, then runs the generated conformance suite against that installed copy with user-site and ambient `PYTHONPATH` disabled. Build/test child-process output is captured inside the product boundary so the command emits exactly one strict JSON receipt on its top-level output stream; pip or unittest chatter must never prefix or trail that receipt. A source-tree-only import is not accepted as project-test success. `noetrium project doctor --project .` always verifies canonical manifest identity, installed Platform provenance, generated files and the downstream public-import boundary. For the author profile it additionally probes the installed public Research Method Host and typed compiler/binding seam. This makes authoring/compilation readiness explicit while runtime execution still requires an injected BindingContribution and an explicit provider/runtime application. For the provider profile it verifies typed Participant/Model/Environment diagnostics, Environment readiness and explicit application binding.

`--project` is profile-aware. The default AUTHOR profile exposes the producer-owned Research Method Host and compiles only when an explicit BindingContribution is supplied; it never searches for or generates `application.py`. The explicit PROVIDER profile may use direct application loading as a Level-2/provider-author escape hatch:

```bash
noetrium run --project ./provider-project run-123 --payload '{"expected_generation":0}'
noetrium inspect --project ./provider-project run-123
```

The provider loader derives the package identity from the canonical manifest and rejects an application module that resolves outside the explicit project root. `--project` and `--application` are mutually exclusive authority sources.

## NPE reference authority

The historical `noetrium_platform.product.operator.reference` workload remains a narrow CLI/distribution smoke fixture only. It persists its own synthetic phase/generation/event state and therefore is **not** Section-37 New Project Experience lifecycle evidence.

Claim-grade NPE reference acceptance composes producer-owned contracts through a downstream-owned binding: the project supplies a typed ROLE03 `RunControlPort`, while the public ROLE06 adapter translates its receipts. The verifier exercises the public Method Host, the explicit binding seam, and the complete generation-fenced `run -> inspect -> stop -> resume -> reconcile -> evidence` lifecycle in separate fresh processes. The historical Operator smoke workload remains excluded.

The clean-room driver is deliberately materialized inside the generated downstream project and imports only `noetrium.contracts`, `noetrium.platform`, and the Python standard library. It owns no Platform authority; it is a deterministic qualification binding whose state is stored at an explicit run-local path and reopened by a fresh process. Missing, malformed or non-finalized lifecycle receipts remain fail-closed.
