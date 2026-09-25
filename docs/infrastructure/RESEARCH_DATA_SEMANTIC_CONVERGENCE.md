# Research Data Semantic Convergence

Policy: Playbook §40–§42. Owner: ROLE05 Environment & Evidence.

## Goal

ROLE05 converges Artifact/Data/Evidence toward one storage-independent research-data path without merging durable authorities. Physical paths, buckets, mounts, and hosts are provider placement state; scientific identity is content/schema/lineage based.

Target flow:

`producer authority -> portable typed identity -> verified storage binding -> read-only query federation -> export/projection`

ROLE03 owns MeasurementDefinition/MeasurementRecord scientific semantics. ROLE05 owns durable Dataset/Artifact backing, verified placement, query/index/export mechanics, and lineage persistence. Query indexes never become Run, Measurement, or Evidence authority.

## Portable Dataset authority

`DatasetVersion` contains `DatasetIdentity`, scope, `content_sha256`, optional schema identity, typed parent `DatasetIdentity` lineage, tags, and metadata. It contains no physical `location`.

SQLite Dataset authority persists the same portable contract. Legacy schemas containing `location`/`digest` fail closed rather than being silently interpreted. Parent lineage is encoded as exact `{dataset_id, version}` identities rather than `"id@version"` strings.

## Verified Artifact placement

Logical `ArtifactRecord` remains storage-independent. `artifact/content` owns typed `ArtifactStorageBinding` placement state and positive CAS generation separately from catalog identity.

`VerifiedArtifactStoragePlacement` is a snapshot proof, not a claim that an externally mutable path stays valid forever. The filesystem verifier requires an absolute existing regular file, streams SHA-256 over the bytes, and rejects missing, unreadable, non-file, unsupported-provider, or digest-mismatched placements.

`bind` and `relocate` re-verify inside the SQLite CAS transaction, and every public `resolve()` re-hashes the current bytes before returning the binding. A verify-to-CAS content race fails closed without advancing authority.

Relocation verifies the destination and may recover from a corrupted old source because logical content identity remains durable. Successful relocation preserves content SHA-256 and increments generation; post-bind, reopen, and destination tamper are detected on authoritative resolve.

## Immutable Artifact content identity

`ArtifactContentIdentity(artifact_id, content_sha256)` is the portable claim-grade content identity owned by the top-level `artifact.api` vocabulary. It intentionally excludes mutable `reference_id`/generation and physical provider/location state.

The `artifact.content` subsystem owns verification/materialization rather than the identity type itself. `compose_artifact_content_identity_resolver(...)` binds Artifact catalog, reference, verified-storage, and provider-owned placement proof behind one `ArtifactContentIdentityResolverPort`. Consumers receive one read-only typed surface: `verify(...)`, `load(...)`, and `snapshot_reference(...)`. A binding row is never sufficient proof by itself: the resolver re-proves current physical bytes for the binding provider/location, and exact artifact identity, immutable catalog digest, binding digest, provider identity, canonical location, and placement proof must agree. Missing authorities, digest drift, unverified placement, foreign facts, and runtime alias impostors fail closed. Storage relocation may change provider/location/generation while the immutable content identity remains unchanged.

`snapshot_reference(...)` is the migration seam for mutable aliases: it verifies the exact `ArtifactReference`, resolves the current artifact, and returns only the immutable verified content snapshot. Later reference retargets/generation changes create a new snapshot and cannot mutate a previously captured scientific identity. The former function-style public entrypoints were deleted rather than retained as compatibility aliases.

## Typed Artifact lineage

`ArtifactRecord.lineage` and `ArtifactLineageEdge` use top-level `ArtifactContentIdentity` values rather than artifact-id strings. Catalog lineage is unique, canonically ordered, and rejects self-lineage; edge identity commits to both artifact id and immutable content SHA-256, so equal names with different content cannot be silently merged. Supporting evidence refs use the same immutable content vocabulary.

SQLite Artifact catalog persists lineage as exact `{artifact_id, content_sha256}` objects and rejects legacy string lineage rows. SQLite lineage authority persists explicit parent/child content digests plus exact typed evidence-content objects. The former artifact-id-only relation schema and string evidence refs fail closed; no compatibility aliases recreate artifact-id-only lineage authority.

Data and ROLE03 must consume this producer-owned value through the published dependency once the clean upstream producer union is consumable; they must not replace it with a mutable `ArtifactReference` alias or a second content authority.

## Typed research-result query federation

`data/query/cross` is a real read-only semantic boundary rather than a generic operation/checkpoint leaf. Public execution is `ResearchResultQuery -> ResearchResultPage` through typed source/query ports.

Queries use typed scientific dimensions and result kinds. Each producer adapter returns an exact `ResearchSourceCut`; callers may pin cuts for repeatable reads. Changed cuts are `STALE`, source failures are `UNAVAILABLE`/`INCOMPLETE`, and unsupported dimensions or result kinds produce typed gaps instead of a misleading complete empty result.

`ResearchResultPage` exposes `matched_count` and `truncated`; any global `limit` truncation forces `complete=False`. Source disposition and diagnostics participate in the input-cut digest, so incomplete or stale reads cannot share the identity of a complete cut.

Dataset and Artifact adapters project producer-owned identities; the federation owns no mutable research truth and exposes no generic `execute`, checkpoint, restore, or state API. Source hard limits are fail-closed as incomplete cuts rather than silent truncation.

## Canonical JSON convergence

ROLE05 consumes the ROLE01 strict finite JSON kernel producer through merge `dfd6801b1c333e3f8014c70235d2205996e55fb8`. Data aliases kernel `strict_finite_json_bytes/text/digest` and `strict_json_loads`; its former local decoder is deleted. Artifact catalog/content/lineage/reference/retention durable record digests use `strict_finite_json_digest` directly.

This keeps one encoding/decoding acceptance authority: valid finite JSON remains byte/digest-identical, while bytes, paths, sets, enums, non-finite values, cycles and other broad canonical values fail before scientific persistence.

## Cross-role dependencies

Resolved in the consumed ROLE01 producer:

- `CSR-ROLE05-ROLE01-PSC02-STRICT-FINITE-JSON-CUTOVER-20260831`: functional strict encode/decode/digest cutover is complete.
- `CSR-ROLE05-ROLE01-ROLE06-SEMANTIC-BOUNDARY-GATE-20260831`: architecture tests no longer hard-code 81 generic leaves, so `data/query/cross` remains a typed semantic boundary without fake execute/checkpoint state.

Open producer/governance dependencies are recorded outside the repository under `outputs/reports/role05/`:

- `CSR-ROLE05-ROLE01-PSC05-DATA-ARTIFACT-CONTENT-REFERENCE-20260831`: ROLE01 `2a22a6e7` now declares the typed Data -> Artifact dependency; official ROLE05 ancestry consumption is sequencing-blocked only by the still-unpushed ROLE03 producer union. Artifact already publishes the immutable identity and resolver.
- `CSR-ROLE05-ROLE03-UNIFIED-RESEARCH-RESULT-READ-PROJECTION-20260831`: ROLE03 now publishes typed read authority for Run/Evidence through `RunControlResearchResultSource`; Trial/Task/Measurement still require their producer-owned read ports before ROLE05 can close the unified read-only federation.

Until those producer decisions land, `run`, `task`, `action`, `observation`, `measurement`, and `evidence` result kinds remain explicitly representable but unsupported sources return typed `NO_SOURCE_CAPABILITY` gaps. ROLE05 does not create a private Run/Measurement registry or restore generic leaf authority.
