# Agent research execution review — 2026-09-09

## Decision

Noetrium remains the single authority for typed model qualification, endpoint
provenance, environment sessions, study scheduling, and artifact finalization.
Downstream methods should bind those authorities once at the experiment-run
boundary and reuse them across assignments.

The first upstream optimization is now implemented on
`refactor/run-scoped-research-validation`: one
`QualifiedModelProjectProvider` materializes one project client per typed
`ModelCapabilityRequirement` digest. Repeated downstream `bind()` calls
reuse that client for the lifetime of the provider. Request-level recording,
prompt/schema provenance checks, endpoint route fencing, response fencing, and
artifact verification remain unchanged.

The workflow layer now has the same explicit lifetime boundary. Built-in
`context_action` and `agent_turn` surfaces are bound once for the active run,
so action-safety/recovery and capability-operation collaborators are not
reconstructed for every decision cycle. A custom surface remains cycle-scoped
unless its factory explicitly declares `reuse_scope = "run"`; this keeps
unknown downstream stateful implementations safe by default.

This is a run-scope pin, not a global cache. A new provider (and therefore a
new experiment run) still reloads the persisted qualification closure and
performs the normal qualification checks.

## Required downstream adoption

SEM should:

1. construct one qualified model binding per experiment run;
2. bind the planner requirement once and reuse the returned public client;
3. construct one bundled Minecraft environment binding per experiment run;
4. open and close one environment session per assignment, resetting the world
   at the assignment boundary;
5. keep per-action effect receipts, per-assignment method checkpoints, and
   finalized result artifacts.

The optimization must not remove assignment isolation, fresh-world reset,
effect verification, request provenance, or final artifact verification.

## Validation consolidation

The execution path is intentionally divided by the identity that can make a
check stale:

| Boundary | Check | Frequency | Safe optimization |
| --- | --- | --- | --- |
| Release/source | taxonomy, architecture, generated schemas, package evidence | source revision | run once per exact release commit |
| Run admission | model qualification closure, participant binding, workflow surface assembly, structural Environment recovery capability | run/session | bind and prove once, then reuse |
| Assignment | fresh environment session/world cut, participant checkpoint, assignment identity | assignment | keep per assignment |
| Action | exact request digest, effect intent slot, provider receipt, reconciliation, commit consumption | external effect | keep per action |
| Result | measurement coverage, finalized artifact stream, evidence/hash closure | result/artifact | keep at finalization |

The run/session capability proof is now memoized in the run-scoped action
surface. A failed proof is never cached, so retrying after a transient setup
failure still rechecks the capability. This removes one structural capability
dispatch from every later decision cycle without weakening any live effect or
scientific-result proof.

## Validation boundary

The remote Linux node must run the focused model-provider tests and the SEM
conformance/smoke suite before this branch is merged. Full Minecraft matrix
execution remains blocked until the live server and a fresh, non-expired model
qualification closure are available. Windows Portable Git remains the final
push/sync path when the remote Commander connection is restored.
