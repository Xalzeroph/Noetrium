# Debug Playbook — Minimal Time-to-Root-Cause

1. Capture the `failure_id`; never debug from screenshot-only text.
2. Run `why` to obtain domain/code/component/stage and exact run/task/decision-cycle/operation coordinates.
3. Inspect the operation timeline and unclosed invocation projection. Temporal adjacency is correlation, not automatic causality.
4. If the failure involves an LLM/model decision, locate its `request_id`, load the `ModelRequestEnvelope`, reconstruct the canonical request body/compiled prompt/tool-schema bundle, and verify the actual model-visible bytes against durable refs.
5. Query `last-writer` for each implicated authoritative state.
6. Run evidence/hash-chain verification. If authoritative evidence is corrupt, stop scientific interpretation and repair evidence first.
7. For external effects inspect effect certainty. `UNKNOWN` means reconcile/observe; never blindly replay.
8. For capability failures distinguish policy rejection from execution outcome. If `execution_completed=True`, do not interpret rejection as “tool never ran”. Respect `retry_safe`.
9. For scope/lifecycle issues inspect active registrations/leases and the owning scope. Do not force-remove a registration that still has active leases; quiescent close/dispose is the contract.
10. For derived-index inconsistencies compare source identity/version and projection start/end watermarks. Rebuild on rewind/drift; never patch the projection into looking current.
11. For model/service interruption execute only the frozen exact-recovery plan. Never change model/revision/engine/dtype/quantization/context during recovery.
12. Fix the smallest owning subsystem, add a direct regression at that boundary, then run Architecture / Silent-Failure / No-Degradation gates and the full suite.

## Model request reconstruction checklist

A valid model-request reconstruction should prove:

```text
request_id
ExecutionContext
ImmutableModelIdentity
prompt generation/id/digest
request_body ContentRef
compiled_prompt ContentRef (if present)
tool_schema_bundle ContentRef (if present)
source artifact/state refs
ModelRequestEnvelope digest
```

The durable reconstruction must byte-match the semantic request submitted by the caller.

## Failure contract

Every important failure should resolve to:

```text
failure_domain
failure_code
component_id
stage
operation_id
run_id / task_id / decision_cycle_id
cause type + digest
correlation refs
state reads/writes
effect certainty
scientific/comparability/integrity risk
recommended mechanical recovery
```

Raw sensitive exception strings are not the stable failure API; safe human text and machine correlation use `error_api` / `failure_api` semantics.
