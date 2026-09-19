# Noetrium system benchmark optimization ledger — 2026-09-15
> Classification: research audit / external design comparison only.\n> This file is not canonical platform architecture.\n\n
## Purpose

This ledger is the persistent control document for benchmark-driven optimization of Noetrium. External repositories are research inputs only; Noetrium keeps its own typed APIs, authorities, lifecycle, evidence and recovery semantics. No external benchmark repository becomes a runtime dependency.

The optimization order is authority-first rather than file-first: understand the canonical system registry, identify one owned responsibility, audit a small benchmark slice, absorb the transferable design into the existing Noetrium authority, test it, remove temporary staging, and commit locally before moving to the next module.

## Frozen architecture invariants

- One primary authority per durable fact or external-effect domain.
- Stable contract plane, runtime plane, durable truth/evidence plane and side-plane observation remain distinct.
- Composition roots assemble providers; API packages expose contracts and ports, not provider selection.
- No global mutable service locator, universal mutable context, duplicate event bus, duplicate agent loop, duplicate checkpoint system, or duplicate execution engine.
- Working hot paths use pre-bound typed references; registry discovery and validation stay off per-step paths.
- Provider failures, observer failures and model uncertainty fail closed where they can affect scientific truth or external effects.
- Downstream projects select typed capabilities and method semantics; they do not rebuild platform lifecycle, evidence, safety, recovery or experiment infrastructure.
- External repositories may be staged only for design audit and are deleted when their module-specific staging is no longer needed.

## Current platform map

The canonical registry currently contains 174 registered nodes across 18 top-level families. The platform is a modular monolith, not 174 services. Registered nodes describe ownership and typed seams; they must not imply one process, one store or one runtime loop per node.

| Family | Nodes | Optimization focus | Benchmark candidates | State |
| --- | ---: | --- | --- | --- |
| platform | 5 | lifecycle/configuration/identity/concurrency | Kubernetes controller-runtime, Backstage backend | candidate |
| governance | 13 | registry, gates, budgets, evolution, schema | Kubernetes API machinery, controller-runtime, Backstage | active |
| scope | 7 | identity, hierarchy, ownership, resolution | Kubernetes API machinery, OpenFGA-style models | candidate |
| portfolio | 5 | workspace/project/program manifests | Backstage catalog, Pants/Bazel workspace models | candidate |
| runtime | 13 | host/process/service/session/toolchain | systemd, Kubernetes kubelet/controller-runtime | candidate |
| resource | 6 | compute, leases, allocation, resolution | Kubernetes scheduler/resource model, Ray | candidate |
| reliability | 7 | effects, failure, recovery, forensics | Temporal, Kubernetes reconciliation | candidate |
| execution | 7 | operation/admission/capability/workflow | Temporal, Prefect/Dagster, Codex | candidate |
| experimentation | 15 | study/run/checkpoint/evaluation/workbench | MLflow, Ray Tune, Hydra, Dagster | candidate |
| model | 16 | request/serving/qualification/deployment | OpenAI Codex, Claude Code, DSH, vLLM | candidate |
| participant | 8 | agent/method/session/capability | OpenAI Codex, Claude Code, DSH | candidate |
| environment | 18 | environment lifecycle and adapters | Gymnasium, PettingZoo, Mineflayer for Minecraft | candidate |
| data | 8 | fact/state/query/projection/dataset | Apache Arrow/DataFusion, DuckDB | candidate |
| artifact | 7 | content/catalog/lineage/reference/retention | MLflow artifacts, DVC/CAS designs | candidate |
| observability | 27 | logging/tracing/telemetry/status | OpenTelemetry Collector | candidate |
| operator | 8 | command/query/incident/maintenance/audit | Kubernetes kubectl/controller patterns | candidate |
| components | 3 | reusable reference harness components | LangGraph only as comparison, not authority | candidate |
| orchestration | 1 | cross-system composition only | controller-runtime Manager, OTel Collector service | candidate |

Candidate means “useful comparison target”, not “audited or absorbed”. Each row advances only after source-level review of the relevant module.

## Module 01 — governance freshness and generated-contract integrity

### Problem observed on node2

At Noetrium HEAD `7451ddbe`, the working-tree architecture gate compared the current 18/156/206/174 topology directly against an old frozen architecture baseline last changed at commit `41bec92e`. The old baseline remains valuable release provenance, but it is not a usable development reference after later accepted mainline changes. The result was a permanently failing local gate even before new work began.

The downstream contract generator also had a fail-open bug: README interface drift set `ok = False`, then the function unconditionally reset `ok = True` before checking other generated files. README-only drift could therefore return success.

### Audited benchmark slices

**kubernetes-sigs/controller-runtime — Manager**

The Manager owns assembly and lifecycle, accepts explicit dependencies through options, and does not turn component registration into business-state ownership. Transferable principle: a governance/composition authority coordinates validation and lifecycle while concrete domain ownership stays elsewhere.

**OpenTelemetry Collector — component factories / service assembly**

Collector factories are separated by typed category maps (receivers, processors, exporters, extensions, connectors, providers), reject duplicate component types, and are supplied to service assembly explicitly. Transferable principle: canonical declarations plus explicit typed assembly beat runtime global scanning and implicit registration.

**Kubernetes generation / observed-state pattern**

The transferable principle is separation between a desired/current development reference and formally accepted durable state. Noetrium applies that principle without copying Kubernetes APIs: working-tree governance compares against the exact Git HEAD cut, while formal Git/release governance continues to use the frozen baseline plus cryptographically bound ROLE00 migration approvals.

### Absorbed design

- Default working-tree architecture analysis now builds an immutable Git `HEAD` source cut and uses its measured architecture complexity only as the development no-growth reference.
- The frozen architecture baseline and ROLE00 migration approval path are unchanged.
- Formal Git verification rejects any attempt to inject the working-tree reference.
- The downstream generator preserves README drift in its final `clean` result instead of resetting it.
- Regression tests cover no-growth behavior and README-only fail-closed generation checks.
- Generated downstream catalog/facades are refreshed from the canonical registry/API exports.

### Acceptance evidence

- Focused tests: `tests/test_architecture_analyzer.py` + `tests/test_downstream_contracts.py`.
- Default architecture gate must pass on the unchanged HEAD topology and fail on any new unapproved complexity growth.
- `scripts/generate_downstream_contracts.py --check` must be clean after regeneration.
- README user-authored edits outside the generated interface block remain unstaged and uncommitted.

## Next audit queue

1. Model/request + participant/agent context/token budget: DSH, OpenAI Codex, Claude Code. Cover separate input/output budgets, overflow compaction/retry, tool-call/result pairing, truncation fail-closed, host facts vs model history.
2. Execution/reliability: operation deadlines, retry/cancel/resume, effect idempotency, reconciliation and checkpoint restoration. Benchmark Temporal plus Codex/Claude tool execution boundaries.
3. Governance/security + execution/capability: capability allowlists, permission decisions, sandbox/tool policy and escalation. Benchmark Codex and Claude Code policy boundaries.
4. Observability + reliability/checkpoint: append-only event evidence, projections, replay and recovery without creating a second event bus. Benchmark Temporal event history and OpenTelemetry only for observation semantics.
5. Experimentation/workbench: compile/freeze binding plans, run-local resources, qualification freshness, pilot-to-formal promotion and downstream author ergonomics.
6. Environment/Minecraft: retain Mineflayer-native capabilities first; explicitly exclude Voyager skill/curriculum/retrieval/executable-skill subsystems from SEM scientific behavior.

Every queue item must end in tests plus a local commit before the next item is considered absorbed.
