from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium import api
from noetrium_platform.composition.research_os_experiment_artifacts import (
    DirectoryResearchOSExperimentArtifactStoreFactory,
)
from noetrium_platform.composition.research_os_experiment import (
    ResearchOSExperimentArtifactStoreBinding,
    ResearchOSExperimentClosure,
    ResearchOSExperimentRuntimeBinding,
    compile_research_os_experiment_closure,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import StrictResearchOSControl
from noetrium_platform.composition.research_os_runtime import (
    CanonicalResearchOSNodeRuntime,
)
from noetrium_platform.composition.research_os_reconciliation import (
    ResearchOSNodeReconciliationProof,
)
from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSImmutableValueAuthority,
)
from noetrium_platform.composition.research_os_values import ResearchOSValueRouter
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.foundation.governance.architecture.api import (
    BindingProof,
    CompositionSubject,
)
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import Sha256Digest, canonical_digest
from noetrium_platform.evidence.artifact.catalog.providers import (
    SQLiteArtifactRegistry,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectIdentity,
    ProjectManifest,
    ProjectProviderBinding,
    ProjectSpec,
    ProjectToolProvenance,
)
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    ResearchBindingRequirements,
    ResearchCapabilityBinding,
    compile_experiment_program,
    compile_research_plan,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementValueKind,
    ReplayLevel,
    ResearchRevision,
    ResearchStudyDefinition,
    StudyExecutionPolicy,
    TaskDefinition,
    StudyMetricObservation,
    TrialBudget,
)
from noetrium_platform.research.experimentation.lifecycle.study.algorithms import (
    BasicStudyMetricAggregator,
)
from noetrium_platform.research.experimentation.lifecycle.run.runtime import (
    DirectoryRunArtifactStore,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphReconciliationDisposition,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _validate_experiment_report(payload):
    report = payload["report"]
    if report["schema"] != "research-os.experiment-report-ref.v2":
        raise ValueError("unexpected experiment report schema")
    manifest = report["manifest"]
    if len(manifest["content_sha256"]) != 64 or len(manifest["generation"]) != 64:
        raise ValueError("experiment report artifact identity is incomplete")
    return None


def _compiled_graph():
    builder = api.ResearchProgramBuilder("paper")
    builder.protocol("study", config={"authority": "experimentation"})
    builder.experiment("main", definitions=("study",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "experiment closure",
    )
    return compile_research_portfolio_graph(revision, portfolio)


def _study_definition(*, seeds=("seed-1",)) -> ResearchStudyDefinition:
    benchmark = BenchmarkTaskSet(
        "benchmark",
        "1",
        "b" * 64,
        "task.v1",
        (TaskDefinition("task-1", "1", "generic", "task.v1", "a" * 64),),
    )
    measurements = MeasurementProtocol(
        "measurements",
        (
            MeasurementDefinition(
                "score",
                "scalar-v1",
                MeasurementValueKind.SCALAR,
            ),
        ),
    )
    return ResearchStudyDefinition(
        "suite",
        "main",
        "study-1",
        "method-program",
        (),
        seeds,
        1,
        measurements,
        benchmark,
        None,
        ResearchBindingRequirements("trial-provider"),
        ExperimentTrialProtocolIdentity("trial.test", "c" * 64),
        ResearchRevision("research-os-revision", "d" * 64),
        StudyExecutionPolicy.serial_shared_v1(
            trial_budget=TrialBudget(
                "standard",
                max_steps=8,
                max_seconds=60.0,
            ),
            replay_level=ReplayLevel.EXACT,
            repetition_timeout_seconds=60.0,
        ),
    )


def _resolution_and_binding(definition: ResearchStudyDefinition):
    requirement = ProjectCapabilityRequirement(
        "trial-provider",
        "experimentation",
        "trial",
        1,
        "1" * 64,
    )
    provider = ProjectProviderBinding(
        "trial-binding",
        "trial-provider",
        "trial.provider",
        "1",
        "2" * 64,
    )
    manifest = ProjectManifest(
        ProjectSpec(
            ProjectIdentity("suite", "1"),
            "program",
            "Suite",
        ),
        "template",
        ProjectToolProvenance("tool", "1", "3" * 64),
        capability_requirements=(requirement,),
        provider_bindings=(provider,),
        study_ids=("study-1",),
    )
    resolution = resolve_research_requirements(definition, manifest)
    proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("experimentation")),
        subject=CompositionSubject.project_subject("suite", "1"),
        requirement_digest=Sha256Digest(canonical_digest(requirement)),
        provider_identity="trial.provider",
        provider_profile_digest=Sha256Digest("4" * 64),
        binding_generation="generation-1",
    )
    binding = ResearchBindingContribution(
        resolution.resolution_digest,
        (ResearchCapabilityBinding("trial-provider", proof),),
    )
    return resolution, binding


def test_experiment_closure_is_existing_compiler_output_bound_to_research_graph() -> None:
    compilation = _compiled_graph()
    node = compilation.node("paper::main")
    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)

    closure = compile_research_os_experiment_closure(
        graph_id=compilation.plan.graph_id,
        graph_digest=compilation.plan.graph_digest,
        research_revision_digest=compilation.plan.research_revision_digest,
        node=node,
        definition=definition,
        resolution=resolution,
        binding=binding,
    )

    assert closure.research_plan.experiment_plan == closure.experiment_program.plan
    assert closure.experiment_program == compile_experiment_program(
        closure.research_plan.experiment_plan
    )
    assert len(closure.closure_digest) == 64
    closure.validate_source(
        graph_id=compilation.plan.graph_id,
        graph_digest=compilation.plan.graph_digest,
        research_revision_digest=compilation.plan.research_revision_digest,
        node=node,
    )


def test_experiment_closure_rejects_cross_revision_or_node_rebinding() -> None:
    compilation = _compiled_graph()
    node = compilation.node("paper::main")
    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)
    closure = compile_research_os_experiment_closure(
        graph_id=compilation.plan.graph_id,
        graph_digest=compilation.plan.graph_digest,
        research_revision_digest=compilation.plan.research_revision_digest,
        node=node,
        definition=definition,
        resolution=resolution,
        binding=binding,
    )

    with pytest.raises(ValueError, match="does not belong"):
        closure.validate_source(
            graph_id=compilation.plan.graph_id,
            graph_digest=compilation.plan.graph_digest,
            research_revision_digest="f" * 64,
            node=node,
        )


def test_closure_constructor_rejects_plan_from_other_scientific_design() -> None:
    compilation = _compiled_graph()
    node = compilation.node("paper::main")
    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)
    closure = compile_research_os_experiment_closure(
        graph_id=compilation.plan.graph_id,
        graph_digest=compilation.plan.graph_digest,
        research_revision_digest=compilation.plan.research_revision_digest,
        node=node,
        definition=definition,
        resolution=resolution,
        binding=binding,
    )
    other_definition = replace(definition, seeds=("seed-2",))
    other_plan = compile_research_plan(
        other_definition,
        resolution,
        binding,
    )

    with pytest.raises(ValueError, match="research plan drifted"):
        ResearchOSExperimentClosure(
            closure.source_graph_id,
            closure.source_graph_digest,
            closure.source_revision_digest,
            closure.source_graph_node_id,
            closure.source_semantic_digest,
            closure.source_definition_digests,
            closure.definition,
            closure.resolution,
            closure.binding,
            other_plan,
            compile_experiment_program(other_plan.experiment_plan),
        )



class _ClosureProvider:
    def __init__(self, definition, resolution, binding) -> None:
        self.definition = definition
        self.resolution = resolution
        self.binding = binding

    def resolve(
        self,
        *,
        graph_id,
        graph_digest,
        research_revision_digest,
        node,
    ):
        return compile_research_os_experiment_closure(
            graph_id=graph_id,
            graph_digest=graph_digest,
            research_revision_digest=research_revision_digest,
            node=node,
            definition=self.definition,
            resolution=self.resolution,
            binding=self.binding,
        )


class _BoundAdapter:
    def execute_bound(self, unit, bindings, plan_digest):
        del bindings, plan_digest
        return tuple(
            StudyMetricObservation(assignment, (("score", 1.0),))
            for assignment in unit.assignments
        )

    def execute_bound_variant(self, assignment, binding, plan_digest):
        del binding, plan_digest
        return StudyMetricObservation(assignment, (("score", 1.0),))


class _ExperimentReconciliation:
    identity_digest = canonical_digest(
        {"reconciliation": "test.experiment-reconciliation.v1"}
    )

    def reconcile(
        self,
        closure,
        *,
        machine_id,
        execution_cut_id,
        graph_node_id,
        semantic_digest,
        lowering_digest,
        attempt_id,
    ):
        del closure, machine_id
        return ResearchOSNodeReconciliationProof(
            execution_cut_id,
            graph_node_id,
            semantic_digest,
            lowering_digest,
            attempt_id,
            ResearchGraphReconciliationDisposition.RETRY,
            "test.experiment-reconciliation",
            (canonical_digest({"proof": attempt_id}),),
        )


class _InlineActor:
    actor_id = "research-os-experiment-test-writer"

    def call(self, operation, fn, /, *args, **kwargs):
        del operation
        return fn(*args, **kwargs)


class _ExperimentArtifactFactory:
    identity_digest = canonical_digest(
        {"factory": "test.execution-cut-artifact-store.v1"}
    )

    def __init__(self, root) -> None:
        self.root = root
        self._stores = {}

    def resolve(self, closure, *, execution_cut_id):
        store = self._stores.get(execution_cut_id)
        if store is None:
            store = DirectoryRunArtifactStore(
                self.root / execution_cut_id,
                run_id=execution_cut_id,
                writer_actor=_InlineActor(),
            )
            self._stores[execution_cut_id] = store
        store_identity = canonical_digest(
            {
                "store": "directory-run-artifact-store.v1",
                "root": str((self.root / execution_cut_id).resolve()),
                "run_id": execution_cut_id,
            }
        )
        return ResearchOSExperimentArtifactStoreBinding(
            closure.closure_digest,
            execution_cut_id,
            store,
            self.identity_digest,
            store_identity,
        )


class _ExperimentRuntimeBindings:
    def __init__(self, artifact_factory) -> None:
        self.artifact_factory = artifact_factory

    def resolve(self, closure):
        return ResearchOSExperimentRuntimeBinding(
            closure.closure_digest,
            closure.experiment_program.plan.plan_digest,
            closure.research_plan.binding_digest,
            _BoundAdapter(),
            BasicStudyMetricAggregator(),
            self.artifact_factory,
            _ExperimentReconciliation(),
            canonical_digest({"adapter": "test.bound-study-execution.v1"}),
            canonical_digest({"aggregation": "basic-study-metric-aggregator.v1"}),
            self.artifact_factory.identity_digest,
            _ExperimentReconciliation.identity_digest,
        )


def test_experiment_artifact_store_binding_is_execution_cut_local(tmp_path) -> None:
    compilation = _compiled_graph()
    node = compilation.node("paper::main")
    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)
    closure = compile_research_os_experiment_closure(
        graph_id=compilation.plan.graph_id,
        graph_digest=compilation.plan.graph_digest,
        research_revision_digest=compilation.plan.research_revision_digest,
        node=node,
        definition=definition,
        resolution=resolution,
        binding=binding,
    )
    pool = ResearchExecutionPool()
    group = pool.open_experiment_group(
        "experiment-artifact-factory-test",
        resource_id="experiment-artifact-factory-test",
    )
    factory = DirectoryResearchOSExperimentArtifactStoreFactory(
        tmp_path / "run-artifacts",
        task_group=group,
    )
    runtime_binding = ResearchOSExperimentRuntimeBinding(
        closure.closure_digest,
        closure.experiment_program.plan.plan_digest,
        closure.research_plan.binding_digest,
        _BoundAdapter(),
        BasicStudyMetricAggregator(),
        factory,
        _ExperimentReconciliation(),
        canonical_digest({"adapter": "test.bound-study-execution.v1"}),
        canonical_digest({"aggregation": "basic-study-metric-aggregator.v1"}),
        factory.identity_digest,
        _ExperimentReconciliation.identity_digest,
    )
    left_cut = "1" * 64
    right_cut = "2" * 64
    try:
        left = runtime_binding.bind_artifacts(
            closure,
            execution_cut_id=left_cut,
        )
        left_again = runtime_binding.bind_artifacts(
            closure,
            execution_cut_id=left_cut,
        )
        right = runtime_binding.bind_artifacts(
            closure,
            execution_cut_id=right_cut,
        )

        assert left.binding_digest == left_again.binding_digest
        assert left.store_identity_digest == left_again.store_identity_digest
        assert left.execution_cut_id == left_cut
        assert right.execution_cut_id == right_cut
        assert left.binding_digest != right.binding_digest
        assert left.store_identity_digest != right.store_identity_digest
        assert left.artifacts.run_id == left_cut
        assert right.artifacts.run_id == right_cut
    finally:
        pool.close()


def test_public_research_os_runs_exact_experiment_program_with_durable_machine_journal(
    tmp_path,
) -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.protocol("study", config={"authority": "experimentation"})
    builder.experiment("main", definitions=("study",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))

    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
    )
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    artifact_factory = _ExperimentArtifactFactory(
        tmp_path / "run-artifacts"
    )
    runtime = CanonicalResearchOSNodeRuntime(
        tmp_path / "machine-state",
        execution_pool=pool,
        experiment_bindings=_ExperimentRuntimeBindings(artifact_factory),
    )
    research_os = bind_portfolio_research_os(
        revisions,
        blobs,
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            ResearchOSValueRouter(()),
            experiment_closures=_ClosureProvider(
                definition,
                resolution,
                binding,
            ),
        ),
    )
    try:
        revision = research_os.commit(portfolio, message="exact experiment")
        receipt = research_os.run(
            api.ResearchExecutionTarget("experiment-execution", revision)
        )
        assert receipt.state == "succeeded"
        assert (tmp_path / "machine-state" / "program-journal" / "machines").is_dir()
        active = graph.active_cut("experiment-execution")
        assert active is not None
        assert receipt.payload["cut_id"] == active.cut_id
    finally:
        pool.close()


def test_experiment_runtime_binding_drift_fails_closed() -> None:
    compilation = _compiled_graph()
    node = compilation.node("paper::main")
    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)
    closure = compile_research_os_experiment_closure(
        graph_id=compilation.plan.graph_id,
        graph_digest=compilation.plan.graph_digest,
        research_revision_digest=compilation.plan.research_revision_digest,
        node=node,
        definition=definition,
        resolution=resolution,
        binding=binding,
    )
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp:
        artifact_factory = _ExperimentArtifactFactory(Path(temp) / "run")
        runtime_binding = ResearchOSExperimentRuntimeBinding(
            closure.closure_digest,
            closure.experiment_program.plan.plan_digest,
            closure.research_plan.binding_digest,
            _BoundAdapter(),
            BasicStudyMetricAggregator(),
            artifact_factory,
            _ExperimentReconciliation(),
            canonical_digest({"adapter": "test.bound-study-execution.v1"}),
            canonical_digest({"aggregation": "basic-study-metric-aggregator.v1"}),
            artifact_factory.identity_digest,
            _ExperimentReconciliation.identity_digest,
        )
        object.__setattr__(runtime_binding, "study_plan_digest", "f" * 64)
        with pytest.raises(ValueError, match="does not belong"):
            runtime_binding.validate_closure(closure)



def test_experiment_report_output_is_only_verified_artifact_reference_manifest(
    tmp_path,
) -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.protocol("study", config={"authority": "experimentation"})
    builder.experiment(
        "main",
        definitions=("study",),
        outputs=(
            api.ResearchOutputSpec(
                "report",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)

    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
    )
    artifact_factory = _ExperimentArtifactFactory(
        tmp_path / "run-artifacts"
    )
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    artifact_blobs = DirectoryArtifactBlobStore(tmp_path / "value-blobs")
    artifact_registry = SQLiteArtifactRegistry(tmp_path / "value-artifacts.sqlite3")
    authority = ResearchOSImmutableValueAuthority(
        artifact_blobs,
        artifact_registry,
    )
    research_os = bind_portfolio_research_os(
        SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3"),
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        control=StrictResearchOSControl(
            graph,
            pool,
            CanonicalResearchOSNodeRuntime(
                tmp_path / "machine-state",
                execution_pool=pool,
                experiment_bindings=_ExperimentRuntimeBindings(artifact_factory),
            ),
            ResearchOSValueRouter((authority,)),
            experiment_closures=_ClosureProvider(
                definition,
                resolution,
                binding,
            ),
        ),
    )
    try:
        revision = research_os.commit(portfolio, message="artifact report")
        receipt = research_os.run(
            api.ResearchExecutionTarget("experiment-output", revision)
        )
        assert receipt.state == "succeeded"
        compilation_cut = graph.active_cut("experiment-output")
        assert compilation_cut is not None
        from noetrium_platform.composition.research_os_values import ResearchOSValueSubject
        subject = ResearchOSValueSubject(
            compilation_cut.cut_id,
            "paper::main",
            "report",
            api.ResearchValueKind.ARTIFACT,
            graph.snapshot(compilation_cut.cut_id).node("paper::main").semantic_digest,
        )
        value_reference = authority.lookup(subject)
        report_ref = authority.resolve(value_reference)
        assert report_ref["schema"] == "research-os.experiment-report-ref.v2"
        finalized = report_ref["manifest"]
        assert len(finalized["content_sha256"]) == 64
        assert len(finalized["generation"]) == 64

        # Same immutable execution is replay/recovery-safe: sealed report files
        # are accepted only after exact content verification.
        second = research_os.run(
            api.ResearchExecutionTarget("experiment-output", revision)
        )
        assert second.state == "succeeded"
        assert authority.resolve(authority.lookup(subject)) == report_ref
    finally:
        pool.close()



def test_experiment_artifact_edge_feeds_evaluation_through_authority_resolution(
    tmp_path,
) -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.protocol("study", config={"authority": "experimentation"})
    builder.metric("validate-report", implementation=_validate_experiment_report)
    builder.experiment(
        "main",
        definitions=("study",),
        outputs=(
            api.ResearchOutputSpec(
                "report",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    builder.evaluation(
        "evaluate",
        definitions=("validate-report",),
    )
    builder.depends(
        "evaluate",
        "main",
        bindings=(
            api.ResearchInputBinding(
                "report",
                "report",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    definition = _study_definition()
    resolution, binding = _resolution_and_binding(definition)

    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
    )
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    artifact_factory = _ExperimentArtifactFactory(
        tmp_path / "run-artifacts"
    )
    value_authority = ResearchOSImmutableValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "value-blobs"),
        SQLiteArtifactRegistry(tmp_path / "value-artifacts.sqlite3"),
    )
    research_os = bind_portfolio_research_os(
        SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3"),
        DirectoryArtifactBlobStore(tmp_path / "portfolio-blobs"),
        control=StrictResearchOSControl(
            graph,
            pool,
            CanonicalResearchOSNodeRuntime(
                tmp_path / "machine-state",
                execution_pool=pool,
                experiment_bindings=_ExperimentRuntimeBindings(artifact_factory),
            ),
            ResearchOSValueRouter((value_authority,)),
            experiment_closures=_ClosureProvider(
                definition,
                resolution,
                binding,
            ),
        ),
    )
    try:
        revision = research_os.commit(
            portfolio,
            message="experiment to evaluation artifact edge",
        )
        receipt = research_os.run(
            api.ResearchExecutionTarget(
                "experiment-evaluation",
                revision,
            )
        )
        assert receipt.state == "succeeded"
        active = graph.active_cut("experiment-evaluation")
        assert active is not None
        snapshot = graph.snapshot(active.cut_id)
        assert snapshot.node("paper::main").state.value == "succeeded"
        assert snapshot.node("paper::evaluate").state.value == "succeeded"
    finally:
        pool.close()
