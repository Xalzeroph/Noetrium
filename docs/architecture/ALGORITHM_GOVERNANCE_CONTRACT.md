# Algorithm Governance Contract

## Complexity classification authority

Algorithm Governance classifies asymptotic control-flow growth conservatively. Structural loop counts remain evidence, but only loops whose cardinality may grow with input contribute an `N` factor. Literal finite iterables and values proven to derive exclusively from finite literal iterables are constant factors. Unknown names, calls, provider results, database results, mutable containers whose bounded provenance is invalidated, and all other unresolved iterables remain input-sized.

Python sort operations contribute `N log N` only when the sorted input cardinality is not statically bounded. Database, I/O, and subprocess calls are classified as loop amplification only when they execute under an unbounded loop; a statically finite control loop does not become `N` merely because it contains an effectful call. This does not estimate the internal complexity of the database or external service itself.

JavaScript function symbols own their own control-flow bodies. Nested callbacks/functions are analyzed as independent symbols and do not inflate the parent symbol. Ordinary brace nesting (`if`, object literals, callback bodies) is not loop nesting. Fixed literal `for...of` masks are constant factors; unresolved iterables remain `N`.

## Fail-closed rules

The classifier must never infer a finite bound from an unknown call or mutable input. Mutation of a previously bounded container invalidates its bounded status. Adversarial tests must prove both sides: finite control loops do not create false `N^2`/database-in-loop findings, while an unknown-cardinality loop containing a database call continues to emit the P1 amplification finding.

Analyzer semantic changes require a new analyzer revision. A reviewed baseline for an earlier revision is intentionally stale and the Algorithm Gate must stop at the parent analyzer-migration blocker before reporting per-symbol regressions. Baseline provenance/replay and externally approved lower-bound migrations are separate typed authorities; changing the classifier does not grant or refresh those authorities.


## Exact source and analyzer identity

Release-authoritative Algorithm Governance uses `algorithm-snapshot.v3`. An exact snapshot binds `source_authority=git`, one exact 40-character Git revision, the deterministic digest of all analyzed source documents, the aggregate language analyzer revision string, and `analyzer_implementation_digest`. The implementation digest is computed from canonical UTF-8 source text for `noetrium_platform/foundation/governance/algorithm/**` plus the shared repository-source API/provider used to select the cut. Checkout-only `CRLF`/`CR` versus `LF` differences are normalized to `LF`; all other text changes remain identity-changing. Raw repository source authority continues to use immutable Git-object/source digests.

`exact=True` is not an alias for "disable cache". The builder requires an immutable `RepositorySourceIndexPort`, verifies that the running Algorithm package physically belongs to the audited repository root, and verifies that the local canonical implementation text identity equals the selected immutable source cut. Dirty analyzer bytes therefore fail before release classification. Advisory cache keys include both the language revision and analyzer implementation digest.

## Baseline provenance and replay

The repository baseline is a reviewed historical observation, not a mutable exemption list. A release gate accepts only `algorithm-snapshot.v3` Git baselines. Before any per-symbol comparison, it checks source/analyzer identity and replays the baseline's exact historical Git revision through the current approved analyzer implementation. The replayed source digest and semantic snapshot digest (all snapshot facts except generation time) must equal the stored baseline. Any legacy schema, stale analyzer revision, changed analyzer implementation, unreconstructible source digest, or replay mismatch yields exactly one parent provenance/migration blocker and an empty symbol diff.

Git-authoritative baseline writes require an external ROLE00 record. The record binds exact source Git SHA, analyzed-source digest, analyzer revision, analyzer implementation digest, and semantic snapshot digest. Local filesystem baselines remain available only for non-release unit tests; they are never accepted as release authority.

## External reviewed migrations

External Algorithm Governance approvals are loaded only when both `NOETRIUM_ALGORITHM_GOVERNANCE_APPROVALS` and `NOETRIUM_ALGORITHM_GOVERNANCE_APPROVALS_SHA256` are supplied. The approval file is SHA-256 bound, strict JSON with duplicate-field rejection, and every record carries its own canonical digest. Authority is exactly `ROLE00`; default decision is `not_approved`.

A lower-bound migration binds one exact symbol, candidate Git SHA/source digest, analyzer revision/implementation digest, old complexity, new complexity, rationale, and review evidence. An exact approved match may reclassify only that complexity transition from blocker to reviewed warning. It does not suppress new P0/P1 findings, risk-score regressions, unrelated symbols, or later source/analyzer revisions. Stale, malformed, rejected, or mismatched records contribute zero authority.

Approval records are decoded once into immutable identity indexes. Baseline acceptance and per-symbol lower-bound approval lookup are constant-time by exact source/analyzer/snapshot identity; the only O(N) approval cost is one-time approval-set construction. This prevents governance authority checks from becoming a scan inside every changed-symbol comparison.

## Historical baseline cutover command

The `baseline` command is exact and requires `--source-revision <git-sha>` for Git-authoritative acceptance. It replays that historical source with the running reviewed analyzer identity and checks the external ROLE00 approval before writing the repository baseline. Omitting the historical revision fails closed; the current producer tree is never substituted implicitly.
