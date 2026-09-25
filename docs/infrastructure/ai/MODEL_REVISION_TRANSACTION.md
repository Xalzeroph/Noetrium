# Model revision transaction authority

ROLE04 owns model revision identity and transition authority under
`model/catalog/revision`. Inference clients, serving routes, and training code do
not own promotion or rollback truth.

The canonical transition is:

`proposal -> durable prepared candidate -> durable committed successor -> promotion | rejection`

Rollback is a separate durable authority event. No phase is inferred from file
presence, endpoint changes, mutable model state, or caller-selected generations.

## Typed identity and evidence

- `ModelRevisionIdentity` binds immutable model identity, revision artifact,
  exact parent revision, and lineage contract.
- `ModelUpdateProposal` binds predecessor, update contract, implementation,
  configuration, training input, randomness, and input evidence references.
- `ModelRevisionEvidence` binds one evidence digest to one exact revision and
  one semantic kind: validation, qualification, evaluation, or rollback trigger.
- `ModelPromotionDecision` binds qualification/evaluation evidence plus the
  promotion policy contract, implementation digest, and configuration digest.

## Durable authority

`SQLiteModelRevisionAuthority` is the ROLE04 local durable implementation. It
uses one SQLite transaction per state transition and stores revision/proposal,
prepared, commit, promotion, rollback, active-revision, and authority-generation
state in one database.

Callers provide only `expected_generation`. The authority compares it with the
current durable generation and allocates the next generation inside the same
transaction. A stale different operation fails with `ModelRevisionConflictError`.
An exact retry returns the previously issued durable receipt without executing
the transition again.

Preparation verifies the authoritative active predecessor and persists the exact
proposal, predecessor, candidate, recovery anchor, and validation plan. Commit
accepts only that persisted prepared object and candidate-bound validation
evidence. Promotion requires the candidate to be the exact committed successor
of the current active predecessor. Rollback requires the failed revision to be
current active and the target to be a committed ancestor in the durable lineage.

Fresh-process reopen reconstructs prepared state and current active identity from
the database. SQLite integrity failure, schema drift, missing durable rows,
digest mismatch, duplicate-key payloads, invalid lineage, and torn/non-database
content fail closed with `ModelRevisionIntegrityError`; they are never repaired
by silently recreating authority state.

## Update/training build topology

A candidate cannot now enter the durable prepare phase as a caller-constructed
`ModelRevisionIdentity`. The update path first produces a typed
`ModelUpdateBuildReceipt` from a `ModelUpdatePlan`.

The plan binds the primary predecessor, open update contract, implementation and
configuration digests, frozen training-input digest, randomness identity,
optional named source revisions, and output-lineage contract. Source roles are
open project/domain text rather than a central train/fine-tune/distill enum.
Additional source revisions are canonicalized by source id; algorithms whose
ordering or weights are material bind those semantics in configuration identity.

`ModelUpdateBuildReceipt` then binds the exact plan, proposal, predecessor,
candidate, producer contract/implementation and non-empty build evidence. Build
evidence binds the exact plan digest and candidate revision digest.
`ModelRevisionAuthorityPort.prepare_successor()` accepts only this build receipt.
The SQLite authority stores the complete receipt in prepared state and replays
its typed/domain validation on fresh-process reopen. `PreparedModelRevision`
retains the exact build-receipt digest, so later commit/promotion lineage stays
bound to the candidate-construction proof.

The SQLite schema is `model-revision-authority.sqlite.v2`. There is deliberately
no v1 compatibility decoder: an old authority database fails schema validation
rather than being reinterpreted under the stronger candidate-provenance contract.

The durable provider consumes ROLE01 Platform Kernel `strict_json_loads` and
`strict_finite_json_bytes` directly. Model owns only its exact field sets,
lineage, plan, build-receipt, CAS, promotion, and rollback semantics; it no
longer owns a second duplicate-key/non-finite/depth JSON acceptance policy.
Malformed BOM, duplicate-key, non-finite, Unicode/domain, and excessive-depth
payloads fail through the shared typed canonical decode authority before Model
domain reconstruction.

## Algorithm-governance constraints

Schema bootstrap executes the fixed v2 DDL statements explicitly inside the
existing authority transaction. It does not loop over database calls and does
not use `executescript`, whose implicit transaction behavior would weaken the
crash-atomic bootstrap boundary.

Rollback ancestry is resolved with one recursive SQLite CTE. Python performs a
single linear validation pass over the returned lineage to reject cycles,
missing parents, invalid digests, and uncommitted revisions. There is no
database I/O inside that validation loop; lineage resolution is `O(D)` in
revision depth and remains fail-closed under corrupted ancestry.
