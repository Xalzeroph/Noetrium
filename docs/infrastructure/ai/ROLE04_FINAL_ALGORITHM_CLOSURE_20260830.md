# ROLE04 Final Algorithm Closure — 2026-08-30

This companion records the final Model/Participant algorithm review under the v5 Algorithm Governance analyzer. It does not modify baseline authority and does not suppress findings.

## True optimizations

- `build_runtime_qualification_receipt` was decomposed into role, time, and evidence policies; the main builder returns to constant control complexity while preserving exact live heartbeat and certificate binding.
- Endpoint SHA-256 identity validation uses fixed-size digest validation instead of per-character loops in request/route constructors.
- `PersistedQualifiedModelEndpointBinding` builds deployment/route/canary indexes once. Construction is linear rather than quadratic; role lookup no longer sorts or rescans all canaries.
- Qualified closure loading compares digest sets without sorting, reducing the loader from `O(N log N)` to `O(N)`.

## Required linear contracts

Several immutable public contracts must inspect every variable-length caller value before publishing a trusted receipt/binding. They therefore declare `Algorithm-Complexity: O(N)` with explicit rationale: deployment qualification application/runtime receipts, host inventory receipt, qualified endpoint canary bindings, `AgentObservation`, and `ConversationMessage`.

The adversarial tests in `tests/test_role04_algorithm_contracts_v1.py` place malformed values at the final element of each variable-length input. Passing requires traversal of the complete input; short-circuiting or claiming `O(1)` would weaken fail-closed validation.

## Deliberately separate work

`qualification_index_worker.py` structured-concurrency migration is owned by the concurrent ROLE04 worker and is intentionally excluded from this isolated commit. `DurableExactRecoveryRunner._run_session` remains a separately reviewed durability-required loop: each recovery transition is persisted inside one `recovery_session()` before/after irreversible effects, and must not be bulked in a way that weakens crash recovery.
