# Participant revision transaction authority

ROLE04 owns Participant topology, architecture and state revision semantics.
Provider/runtime layers may execute those Participants, but they cannot synthesize
revision generations or rewrite current revision truth.

The durable transition is:

`proposal -> validated typed transition -> durable prepared candidate -> durable commit/current revision`

`SQLiteParticipantRevisionAuthority` stores proposal, predecessor, candidate,
transition, prepared state, commit, current revision and authority generation in
one SQLite authority. `expected_generation` is caller input; the successor
generation is allocated by the authority inside the same transaction.

## Exact transition semantics

Topology and architecture transitions are not accepted merely because their
from/to digests match. Every declared changed member/component is compared with
the actual predecessor and candidate objects, and the complete set of changed
identities must be reconstructed by the change list.

State transitions bind the open update contract and migration adapter. If state
checkpoint compatibility changes, a migration adapter is mandatory before the
candidate can enter prepared durable state.

## Checkpoint compatibility facets

Revision identity and checkpoint compatibility are intentionally different.

- topology compatibility binds topology id plus participant ids/roles;
- architecture compatibility binds participant id plus component ids/state-schema ids;
- state compatibility is a typed `ParticipantStateCompatibility` binding the
  state contract, schema digest, codec contract and codec implementation digest.

Implementation/configuration/binding changes can therefore create a new exact
revision without automatically invalidating recoverable state. Conversely, a
schema/codec change cannot be hidden inside an otherwise similar revision.

## Durability and failure semantics

Fresh-process reopen reconstructs pending prepared transitions and the committed
current revision. Exact retries return the original durable prepare/commit
result. A different operation using a stale generation fails with
`ParticipantRevisionConflictError`.

Validation evidence is typed and revision-bound; a validation digest for the
predecessor cannot validate the candidate. SQLite integrity errors, table/schema
drift, missing referenced objects, digest drift, unsupported revision kinds and
malformed transition payloads fail closed with `ParticipantRevisionIntegrityError`.
No corrupt authority is silently recreated.

## Algorithm-governance constraints

Participant revision schema bootstrap executes its fixed DDL statements
explicitly within the existing SQLite transaction rather than issuing database
calls from a loop. The fixed statement count is authority-schema work, not an
input-sized algorithm, and avoiding `executescript` preserves the surrounding
crash-atomic transaction semantics.

## Shared strict JSON authority

The durable Participant revision provider consumes Platform Kernel
`strict_json_loads` and `strict_finite_json_bytes` directly. Participant owns
its revision/transition field sets and compatibility rules, but not a second
JSON duplicate-key, non-finite, Unicode/domain, or depth policy. Corrupt durable
payloads therefore fail through the same typed canonical decode authority used
by the rest of the converged Platform boundary before Participant reconstruction.
