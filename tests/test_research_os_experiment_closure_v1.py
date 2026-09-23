from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium import api
from noetrium_platform.composition.research_os_experiment import (
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
from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSArtifactValueAuthority,
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
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


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


class _InlineActor:
    actor_id = "research-os-experiment-test-writer"

    def call(self, operation, fn, /, *args, **kwargs):
        del operation
        return fn(*args, **kwargs)


class _ExperimentRuntimeBindings:
    def __init__(self, artifacts) -> None:
        self.artifacts = artifacts

    def resolve(self, closure):
        return ResearchOSExperimentRuntimeBinding(
            closure.closure_digest,
            closure.experiment_program.plan.plan_digest,
            closure.research_plan.binding_digest,
            _BoundAdapter(),
            BasicStudyMetricAggregator(),
            self.artifacts,
            canonical_digest({"adapter": "test.bound-study-execution.v1"}),
            canonical_digest({"aggregation": "basic-study-metric-aggregator.v1"}),
            canonical_digest(
                {
                    "artifact_store": "directory-run-artifact-store.v1",
                    "run_id": self.artifacts.run_id,
                }
            ),
        )


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
    run_artifacts = DirectoryRunArtifactStore(
        tmp_path / "run-artifacts",
        run_id="experiment-execution",
        writer_actor=_InlineActor(),
    )
    runtime = CanonicalResearchOSNodeRuntime(
        tmp_path / "machine-state",
        execution_pool=pool,
        experiment_bindings=_ExperimentRuntimeBindings(run_artifacts),
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
        artifacts = DirectoryRunArtifactStore(
            Path(temp) / "run",
            run_id="drift",
            writer_actor=_InlineActor(),
        )
        runtime_binding = ResearchOSExperimentRuntimeBinding(
            closure.closure_digest,
            closure.experiment_program.plan.plan_digest,
            closure.research_plan.binding_digest,
            _BoundAdapter(),
            BasicStudyMetricAggregator(),
            artifacts,
            canonical_digest({"adapter": "test.bound-study-execution.v1"}),
            canonical_digest({"aggregation": "basic-study-metric-aggregator.v1"}),
            canonical_digest({"artifact_store": "drift"}),
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
    run_artifacts = DirectoryRunArtifactStore(
        tmp_path / "run-artifacts",
        run_id="experiment-output",
        writer_actor=_InlineActor(),
    )
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    artifact_blobs = DirectoryArtifactBlobStore(tmp_path / "value-blobs")
    artifact_registry = SQLiteArtifactRegistry(tmp_path / "value-artifacts.sqlite3")
    authority = ResearchOSArtifactValueAuthority(
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
                experiment_bindings=_ExperimentRuntimeBindings(run_artifacts),
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
        assert report_ref["schema"] == "research-os.experiment-report-ref.v1"
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
