# ROLE 03 Cross-System Change Requests

## CSR-03-08A-effect-reconciliation

- request_id: `CSR-03-08A-effect-reconciliation`
- requester_system: `execution_operations`
- target_system: Reliability / effect reconciliation owner
- problem: Execution can durably classify an operation as `UNKNOWN_EFFECT`, but reconciliation truth must not be implemented independently inside Execution.
- root cause: generic operation lifecycle and Reliability effect reconciliation do not yet share one explicit typed handoff contract.
- current contract: workflow-specific Reliability effect APIs can reconcile prepared effects; generic `OperationOwner` records only certainty projection.
- required capability: typed request/response contract that resolves a stable `EffectId` to `EXECUTED` or `NOT_EXECUTED` with evidence identity.
- proposed contract: Reliability-owned reconciliation port consumed by an Execution composition adapter; no Reliability provider implementation in Execution.
- affected callers: generic durable operation orchestration and future workflow resume/reconciliation adapters.
- authority impact: Reliability remains sole reconciliation authority; Execution remains operation/effect-certainty projection authority.
- persistence impact: response evidence must be stably referenceable from Operation recovery without duplicating Reliability durable state.
- failure/recovery impact: prevents blind retry after ack loss and makes unresolved reconciliation explicitly blocking.
- scientific semantics impact: no success claim may be inferred from operation state while effect certainty is unresolved.
- breaking change: likely yes for any future generic reconciliation facade that currently returns untyped payloads.

## CSR-03-GOV-workspace-source-drift

- request_id: `CSR-03-GOV-workspace-source-drift`
- requester_system: `execution_operations`
- target_system: Governance / Supervisor workspace authority
- problem: worker-start `WORKSPACE_MANIFEST.md` / `projects/PROJECTS.yaml` source SHA did not match actual canonical Git HEAD.
- root cause: generated/curated workspace metadata was not synchronized with the current canonical branch state.
- current contract: Source-of-Truth rules state actual Git wins over stale historical metadata.
- required capability: regenerate/update workspace source identity from the exact canonical repository state under Governance/Supervisor ownership.
- proposed contract: workspace manifest generation/validation should fail when recorded repository SHA differs from resolved canonical Git HEAD unless an explicit staged-state reason is present.
- affected callers: all Workers resolving baseline/source identity.
- authority impact: no change; Governance retains shared metadata authority and Git remains runtime source truth.
- persistence impact: workspace metadata only.
- failure/recovery impact: prevents stale evidence or tests from being accidentally attributed to the wrong source revision.
- scientific semantics impact: indirect but material for exact-source experiment evidence.
- breaking change: no production API change; validation may newly fail stale workspace metadata.

## CSR-03-07-jsonl-multiprocess-rotation

- request_id: `CSR-03-07-jsonl-multiprocess-rotation`
- requester_system: `execution_operations`
- target_system: Observability logging owner, with Platform durability owner review
- problem: Windows multiprocess JSONL rotation intermittently loses a segment between existence check and durable replacement, causing writer-process failure.
- root cause: the rotation transaction currently relies on cross-process exclusion plus `exists() -> flush/replace`; observed execution proves the source segment can disappear before `_flush_file(source)`, so the effective transaction boundary is insufficient on Windows.
- current contract: `JsonlLogStore.append()` holds `InterprocessFileLock` and calls `durable_replace_file` for numbered segments.
- required capability: one verified cross-process rotation transaction that cannot operate on stale segment identity and cannot silently lose/overwrite records.
- proposed contract: Observability owns segment-generation/rotation semantics; Platform durability provides an atomic/identity-aware replace primitive or corrected lock semantics as needed after owner-level root-cause instrumentation.
- affected callers: all multiprocess writers using rotated `JsonlLogStore`; failure surfaced through task-group/actor execution but is outside Execution ownership.
- authority impact: no Execution authority change; Observability retains log storage truth and Platform retains generic durable-file/lock primitives.
- persistence impact: potential loss or failed publication of rotated log segments; must be fixed without treating a missing source as harmless success.
- failure/recovery impact: current writer process aborts on `FileNotFoundError`; retry safety is uncertain because another writer may already have advanced segment generations.
- scientific semantics impact: logs are observation, not scientific truth, but missing diagnostic evidence can invalidate auditability and release/live evidence completeness.
- breaking change: potentially internal storage/lock protocol change; external log query/append semantics should remain unchanged.

### Reproduction evidence

- ROLE 03 latest working tree: 12 repeated Windows runs of `test_multiple_processes_append_and_rotate_without_overwrite` produced 2 failures.
- Exact worker base `e0003c98ffa873a8d25428de8416f028bae99a99`, exported with `git archive`: the same test produced 1 failure in 12 runs.
- Latest full Windows repository run: `1131 passed, 6 skipped, 4 subtests passed, 1 failed`; the sole failure was this test.
- Failure variants observed: rotated segment disappeared before durable flush (`FileNotFoundError`) and rotated segment could not be opened for flush (`PermissionError`).
- Conclusion: reproducible pre-existing cross-system race; ROLE 03 does not modify the implicated Observability/Platform paths.
