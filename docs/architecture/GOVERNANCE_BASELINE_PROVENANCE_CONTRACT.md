# Governance Baseline Provenance Contract

## Scope

This contract governs the Concurrency and Performance release baselines. It is additive to Algorithm Governance, which has a richer symbol-level lower-bound migration authority. The shared rule is that a baseline is a reviewed projection of one immutable Git source cut under one immutable analyzer implementation identity; a revision label alone is never authority.

## Baseline v2 identity

A Concurrency or Performance baseline v2 records the lane, immutable Git source revision, reconstructible lane source digest, analyzer revision, analyzer implementation digest, the blocker fingerprints observed by replay on that historical source cut, and the separately reviewed accepted blocker-fingerprint set. The semantic baseline digest is canonical over exactly those fields. Observed and accepted fingerprints are sorted/unique, and accepted fingerprints must be a subset of observed fingerprints. Generated timestamps and local filesystem paths are not part of authority.

Analyzer implementation identity uses the canonical source-text digest for the owned governance lane package. Only CRLF/CR to LF normalization is permitted so a clean Windows and Linux checkout of identical Git text has one implementation identity. Raw repository source authority remains Git-object/source-byte based.

## Exact gate behavior

Release and baseline commands use an immutable `GitRepositorySourceTree`; ReleaseQuality passes the same frozen `RepositorySourceIndexPort` to Architecture, Algorithm, Concurrency and Performance. The running lane implementation must come from the audited repository root and its canonical implementation digest must equal the immutable Git cut.

A legacy baseline, missing Git provenance, analyzer implementation drift, historical source-digest mismatch, or historical observed-blocker mismatch stops the lane at one parent provenance blocker. The gate does not emit child producer regressions until baseline provenance is reconstructible. Reproducible observation is not acceptance: after provenance is valid, release headroom is computed only from the reviewed accepted set, so historical hazards that were never accepted continue to block even when replay proves they predate the current producer.

## Baseline acceptance authority

A Git-authoritative baseline cannot be written merely by invoking `baseline`. ROLE00 must supply an external `governance-baseline-approval.v1` record bound to lane, exact source SHA/digest, analyzer revision/implementation digest and semantic baseline digest. The approval file itself and every record are SHA-256 bound; stale, wrong-lane, malformed, duplicate-identity or tampered approvals contribute zero authority.

Filesystem-mode component tests may create local baselines for test isolation, but those baselines are not release authority and cannot satisfy an exact Git gate.

## Replay invariant

Baseline migration must preserve the frozen business comparison source. A provenance migration replays that historical Git revision with the reviewed current analyzer implementation, records the resulting observed set, carries forward only blocker fingerprints that the prior reviewed authority actually accepted, and requires ROLE00 approval before replacing the repository baseline. It must not reinterpret newly observed historical hazards as accepted debt and must not baseline the current producer tree merely to erase newly observed debt.

## External approval transport

The shared ROLE00 approval set is supplied out-of-repository through `NOETRIUM_GOVERNANCE_BASELINE_APPROVALS` together with `NOETRIUM_GOVERNANCE_BASELINE_APPROVALS_SHA256`. Supplying only one is invalid. Git discovery for exact source authority uses the existing `NOETRIUM_GIT_EXECUTABLE` route when required.

## Historical baseline cutover command

The `baseline` command is exact and requires `--source-revision <git-sha>` for Git-authoritative acceptance. It replays that historical source with the running reviewed analyzer identity and checks the external ROLE00 approval before writing the repository baseline. Omitting the historical revision fails closed; the current producer tree is never substituted implicitly.

## Public dependency seam

The canonical Concurrency/Performance baseline semantic digest is a `noetrium_platform.foundation.governance.api` contract. Lane runtime services consume that public API and never import sibling `governance.runtime` implementation. Lane implementation fingerprinting remains a composition/runtime concern. Architecture must reject any reintroduction of a concrete sibling-runtime dependency.
