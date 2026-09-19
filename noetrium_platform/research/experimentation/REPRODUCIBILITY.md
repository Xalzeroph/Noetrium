# Experiment reproducibility authority

ROLE 03 owns the frozen run/checkpoint/evidence identities that connect executable work to reproducible experiment records.

## Run launch manifest

The `RunLaunchManifest` is the launch identity for release, prompt/model deployment, host, participant inventories, experiment specification, command, configuration, seed, and composition plans.

Its persisted wire format is an exact versioned envelope:

- `schema_version = "5"`
- `manifest = { ... exact RunLaunchManifest fields ... }`

Schema v5 keeps the required canonical `project_manifest_digest` and binds a required typed `RunResearchSemanticsReference` from `experimentation.identity`. That reference freezes the compiled research-plan, Study/ExperimentPlan, Measurement Protocol, Trial Protocol, exact method-implementation digest, intervention, participant topology/schedule, revision, and replay identities with explicit applicable/absent facets. Older schemas are intentionally rejected rather than upgraded implicitly.

Unknown, missing, extra, or untyped envelope/manifest fields fail decoding. Unsupported schema versions and semantically equivalent noncanonical bytes fail closed. The encoded v5 bytes are therefore part of frozen launch authority; there is no implicit forward-compatibility path.

The canonical `RunLaunchManifest.digest()` is the stable launch/source identity consumed by evidence publication.

## Run artifact finalization authority

Mutable run artifacts are not scientific evidence merely because a caller knows a path. `DirectoryRunArtifactStore.finalize()` is the authority boundary that snapshots a completed artifact and emits a typed `RunArtifactSnapshotReceipt`.

A snapshot receipt binds the run ID, run-local artifact reference, artifact kind, logical generation, content SHA-256, byte size, and authoritative record count for record streams. Generation is derived only from logical run/artifact identity plus authoritative content facts; it never contains device, inode, mtime, or ctime. A complete backup restored under a different root or filesystem therefore preserves the same scientific artifact identity.

The per-reference seal is the single durable finalization commit point and is published first with the Platform `atomic_replace_bytes` durability authority. Once the seal exists, normal publish/append operations fail closed even if generation-index publication later fails or the store is reopened. The generation ledger is only a derived lookup index: reopen/idempotent finalization recreates a missing index and repairs a corrupt one from the authoritative seal.

`verify_finalized()` does not trust the receipt alone. It requires the durable seal and re-snapshots the current artifact; if a generation index exists it must agree, but absence of that derived index cannot reopen or invalidate sealed authority. Missing/unfinalized artifacts, receipt forgery, content/count drift, run mismatch, or a non-identical-content restore fail closed. Byte-identical backup/restore or replacement remains the same logical generation by design.

The directory provider performs the O(n) content hash/record-count pass at finalization/verification, not after every JSONL append. Append throughput therefore remains single-writer sequential I/O without a per-record full-file rehash.

## Scientific evidence identity

`EvidenceBundleManifest` schema version 2 binds evidence to both `run_id` and the exact SHA-256 `run_manifest_digest`.

Raw evidence streams no longer carry caller-asserted `artifact_ref`, `record_count`, and `content_sha256` fields. Each `EvidenceStreamDescriptor` embeds the artifact authority's typed `RunArtifactSnapshotReceipt`; the bundle rejects receipt/run identity drift and requires record-stream receipts with authoritative counts.

For `COMPLETE` publication, `RunArtifactEvidenceBundlePublisher` verifies every stream receipt through `RunArtifactVerificationPort` before writing the manifest. A hand-constructed descriptor, an existing-but-unfinalized path, or a finalized stream that later changes cannot authorize COMPLETE evidence.

The evidence manifest itself is atomically published and finalized through the same run-artifact authority. `EvidenceBundleReceipt` preserves the typed finalized manifest `RunArtifactSnapshotReceipt` together with `run_id` and `run_manifest_digest`; it does not collapse the manifest authority back into caller-supplied path/hash strings. Publication replay is idempotent only when the existing sealed manifest has the identical authoritative content digest.

An optional `source_checkpoint_id` can bind evidence to a specific checkpoint cut. Raw source-of-truth streams remain separate from rebuildable `DerivedEvidenceArtifact` projections, and derived artifacts list the exact source stream IDs they depend on.

## Checkpoint transaction

Workload restore validates manifest identity, component topology, codec/schema identity, payload references, and payload integrity before mutation.

Before apply, every component preimage is captured. Restore then applies components in manifest order. On failure, attempted components are rolled back in reverse order.

A successful rollback reports `ROLLED_BACK`; any rollback failure reports state certainty `UNKNOWN`. Partial mutation is never silently accepted as authoritative state.

Workload checkpoint manifest schema v3 binds run/study/workload/branch, source cut, environment generation, method generation, task manifest, the exact `checkpoint_compatibility_digest`, execution cut, and component payload digests. The compatibility digest contains only state/recovery-relevant research facets. Method implementation, revision, topology, intervention, Trial Protocol, schedule, or replay drift fail before restore mutation; Measurement/Analysis-only changes do not invalidate a compatible checkpoint.

`RunCheckpointManifestCodec` treats canonical JSON bytes as part of immutable checkpoint authority: a payload must decode to the exact typed manifest, match its digest, and byte-for-byte equal the canonical re-encoding. Semantic-equivalent pretty/reordered JSON is corruption rather than an alternate representation.

`experimentation.checkpoint.composition.build_project_run_checkpoint_store(project_state_root)` is the public project composition seam for the owner-defined crash-durable checkpoint provider. It places generic run checkpoints beneath the explicit project state root and returns only the public `RunCheckpointStore` contract; downstream common-path source need not import `experimentation.checkpoint.providers` or reproduce checkpoint durability.

## Durable generic run control

`experimentation/run/control` is the operator-facing effect/evidence coordinator for `run`, `inspect`, `stop`, `resume`, `reconcile`, and `evidence`. It is **not** an independent lifecycle authority. The authoritative run lifecycle is the shared journal-backed `RunMachine`.

Every state-changing request is fenced by `expected_revision`, which is the current RunMachine revision. `RunControlReceipt.machine_cut` exposes the accepted Machine head; `control_revision` is derived from that cut. Run identity, experiment identity, and launch-manifest identity are bound into the RunMachine, with the launch manifest journal-bound once and then immutable.

Effectful lifecycle actions use prepared-before-effect Machine transitions. `run.control.prepare` is accepted by the Machine Journal before the lifecycle provider may perform the external effect. The Machine enters `RECOVERY_REQUIRED` with an identity-bound pending operation. After an authoritative provider outcome, `run.control.resolve` commits the terminal phase. There is no directory control ledger, terminal-record stream, or parallel control generation.

A crash or uncertain provider result therefore leaves the pending operation in RunMachine state. Replaying the same operation identity does not reissue the external effect; a conflicting operation is rejected. Reconciliation consumes ROLE02 effect certainty and may resolve the pending operation only when the external outcome is authoritative. `UNKNOWN`, possible effect certainty, or verification-required evidence remains recovery-required.

`inspect` and `evidence` are read-only with respect to RunMachine state. `resume` additionally binds the exact checkpoint manifest digest and restore decision-cycle identity. Evidence replies accept only same-run/same-manifest `EvidenceBundleReceipt` values whose manifest artifact verifies through `RunArtifactVerificationPort`.

## New-project public construction and outcome authority

`noetrium_platform.research.experimentation.api.ProjectRunDefinition` is the common project-facing construction boundary. It consumes only the narrow public ROLE 01 project-manifest projection (`identity.project_id`, `study_ids`, `semantic_digest`) and joins that authority with the existing `ExperimentSpec`, `StudyProtocol`, `ExperimentRunSpec`, `RunIdentity`, and `RunLaunchManifest` authorities. It rejects project/experiment/study/repetition/task-manifest/seed/run/manifest identity drift. `RunLaunchManifest.project_manifest_digest` must equal the canonical project manifest semantic digest, so durable run-control and evidence identity remain bound to the exact project configuration after construction. The `definition_digest` is a reproducible projection of those existing authorities; it owns no lifecycle or persistence state and does not parse or persist ProjectManifest bytes.

The same public package re-exports the producer-owned `RunControlPort` request/receipt contracts used by Operator and downstream projects. Projects therefore do not need to assemble checkpoint, workflow, or run-control stores in common-path code. Runtime composition injects one `RunControlPort`; all six application actions project or coordinate against the same shared RunMachine authority.

Every `RunControlReceipt` carries an explicit `RunOutcomeProjection`. Execution outcome is derived only from authoritative RunMachine phase, task outcome remains `NOT_EVALUATED` unless a task authority is added in a future version, evidence validity is `NOT_OBSERVED`, `NOT_FINALIZED`, or `FINALIZED_VALID` according to the evidence command/finalized receipt, and scientific validity remains `NOT_EVALUATED`. The receipt rejects contradictory or caller-forged cross-authority outcomes. Consequently execution success, task success, evidence validity, and scientific validity cannot collapse into one boolean or status string.

## Author research compilation and neutral Trial lifecycle

`noetrium_platform.research.experimentation.api` exposes a side-effect-free author research boundary. Level-0 `ResearchStudyDefinition` records scientific design, Benchmark/TaskSet cut, factors, seeds/repetitions, Trial budget, Measurement Protocol, participant/method/capability requirements, and execution policy without choosing concrete providers. `resolve_research_requirements()` validates those requirement IDs against the ROLE01 ProjectManifest projection; a separate `ResearchBindingContribution` supplies exact participant/provider/model/prompt generations. `compile_research_plan()` joins those typed passes and freezes factor x seed x repetition x task assignments into `ExperimentPlan.plan_digest` without starting processes, opening sessions, writing checkpoints, or invoking RunControl.

Identity is intentionally stratified. Scientific design, participant design, binding requirements, exact provider binding, exact method implementation, execution policy, Benchmark cut, assignments, Measurement semantics, topology/schedule, revision, and replay each have named identities; the total research-plan digest is only a closure. `diff_research_plans()` reports facet-level changes and checkpoint compatibility rather than treating every edit as scientific or execution equivalence.

`BenchmarkTaskSet` separates immutable task content and split membership from `TaskGraph` dependency/retry semantics and `TrialBudget`. `MeasurementProtocol` is the paper-general raw-output schema with scalar, boolean, categorical, structured, sequence, distribution, matrix, text-judgement, and typed content-reference values. `MeasurementRecord` binds the exact scientific Measurement contract plus project/study/run/assignment/producer/intervention/revision and typed Artifact lineage.

Digest-bearing research fields are strict canonical identities: material `*_digest` values are lowercase SHA-256 and are validated through the shared Platform kernel primitive rather than permissive non-empty strings or local validators. `BenchmarkTaskSet` split membership is also execution-significant: the declared `TaskSetSplit.task_ids` order is the exact task order used by the compiler when expanding assignments, so two differently ordered split cuts cannot collapse to the same execution projection.


`MeasurementCut` can pin raw Measurement records, portable ROLE05 `DatasetVersion.content_sha256` identities, and COMPLETE Evidence manifests without importing physical dataset location into scientific identity. `AnalysisDefinition` separately freezes projector/version/implementation/configuration/filter/grouping/comparison semantics over an immutable cut; `AnalysisResult` binds that definition and input cut to derived output content. Changing analysis or storage placement therefore does not imply a rerun of raw trials.

`TrialExperimentProgramBinding` is the neutral runtime boundary. Agent/environment loops, offline scoring, and project-defined custom state machines implement the same open `ExperimentTrialProtocolIdentity`/`TrialProviderPort` contract and return typed Measurement records plus typed Artifact references. Planner/memory workload code remains an Agent archetype rather than generic Experimentation semantics. Built-in no-config Trial protocols use the canonical digest of `{}`, never an empty-string identity sentinel.

Participant topology is a pure public Experimentation value object; Research Compiler is a pure Study API transformation; runtime executors require explicit runtime imports. Top-level `study` and `run` packages do not implicitly load concrete runtime/provider layers.

The historical `noetrium_platform.research.scientific` scaffold had no independent store, provider, lifecycle, schema, or external production consumer and is merge-deleted into Experimentation. Generic trial protocol types use `Trial` terminology and no compatibility aliases preserve the removed scientific-cycle API. Section 42 Artifact/Data references remain producer-owned: Experimentation consumes ROLE05 public identities/verifiers and requires the canonical `experimentation -> artifact` topology declaration from ROLE01 rather than duplicating Artifact authority.

## Validation rule

Persistence/checkpoint/recovery/evidence-finalization changes require Windows plus Server2 validation from the same committed SHA. Protected SEM execution roots, GPU0/1, and the Qwen endpoint are outside this validation path.

### Algorithm-quality note
Fixed-cardinality effect identity validation is expressed as explicit constant-time checks rather than iterable scans. Evidence-stream manifest validation performs run binding, ordering, authoritative-source, and complete-stream checks in one O(N) collection pass; the manifest constructor does not add a second stream traversal.
