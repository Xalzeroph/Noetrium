from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_checkpoint_store import (
    DirectoryResearchOSGraphCheckpointStore,
)
from noetrium_platform.composition.research_os_execution import StrictResearchOSControl
from noetrium_platform.composition.research_os_experiment import (
    ResearchOSExperimentClosureMissing,
)
from noetrium_platform.composition.research_os_runtime import (
    CanonicalResearchOSNodeRuntime,
    CanonicalResearchOSRuntimeUnsupported,
)
from noetrium_platform.composition.research_os_values import (
    ResearchOSValueReference,
    ResearchOSValueRouter,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRuntimePortInventory,
)


def _source():
    return {"value": 7}


def _metric(payload):
    return {"score": payload["source"]["value"] + 1}


def _benchmark():
    return ("task",)


def _source_v2():
    return {"value": 11}


def _stable():
    return {"stable": 1}


def _capability_return(request: api.MethodNodeRequest) -> api.MethodNodeResult:
    return api.MethodNodeResult(value=None)


def _capability_program_factory() -> api.MethodProgram:
    identity = api.MethodProgramIdentity(
        api.MethodIdentity("test.capability-method", "1", "1", "1"),
        canonical_digest({"capability": "test.echo"}),
    )
    return (
        api.MethodProgramBuilder(identity, entrypoint="invoke")
        .capability(
            "invoke",
            "test.capability.invoke",
            "test.echo",
            ("return",),
            effect_class=api.EffectClass.PURE,
        )
        .return_node("return", "test.capability.return", _capability_return)
        .build(
            required_capabilities=("test.echo",),
            required_runtime_ports=(api.MethodRuntimePort.CAPABILITIES,),
        )
    )


@dataclass
class _EchoCapability:
    calls: int = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({"provider": "test.echo", "version": 1})

    def describe(self, capability_id: str) -> api.CapabilityDescriptor:
        if capability_id != "test.echo":
            raise KeyError(capability_id)
        return api.CapabilityDescriptor(
            "test.echo",
            "1",
            "json",
            "json",
            effect_class=api.EffectClass.PURE,
            deterministic=True,
        )

    def invoke(self, request: api.CapabilityRequest) -> api.CapabilityResult:
        if request.capability_id != "test.echo":
            raise KeyError(request.capability_id)
        self.calls += 1
        return api.CapabilityResult("test.echo", {"ok": True, "calls": self.calls})


@dataclass
class _DataAuthority:
    authority_id: str = "data.authority"
    supported_kinds: frozenset[api.ResearchValueKind] = frozenset(
        {api.ResearchValueKind.DATA}
    )
    rows: dict[str, JsonValue] = field(default_factory=dict)

    def publish(self, subject, value):
        frozen = freeze_json(value)
        self.rows[subject.subject_digest] = frozen
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            subject.subject_digest,
            canonical_digest(frozen),
        )

    def lookup(self, subject):
        value = self.rows[subject.subject_digest]
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            subject.subject_digest,
            canonical_digest(value),
        )

    def resolve(self, reference):
        return self.rows[reference.authority_ref]

    def reuse(self, source, target):
        value = self.resolve(source)
        self.rows[target.subject_digest] = value
        return ResearchOSValueReference(
            target,
            self.authority_id,
            target.subject_digest,
            canonical_digest(value),
        )

    def reuse_proof(self, reference):
        return canonical_digest(
            {
                "authority_id": self.authority_id,
                "reference_digest": reference.reference_digest,
            }
        )


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def _portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("source-method", implementation=_source)
    builder.metric("metric", implementation=_metric)
    builder.node(
        "source",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("source-method",),
        outputs=(
            api.ResearchOutputSpec("data", api.ResearchValueKind.DATA),
        ),
    )
    builder.evaluation(
        "evaluate",
        definitions=("metric",),
        outputs=(
            api.ResearchOutputSpec("result", api.ResearchValueKind.DATA),
        ),
    )
    builder.depends(
        "evaluate",
        "source",
        bindings=(
            api.ResearchInputBinding(
                "source",
                "data",
                api.ResearchValueKind.DATA,
            ),
        ),
    )
    return api.ResearchPortfolio("suite", (builder.freeze(),))


def _capability_portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("capability-paper")
    builder.method_program_factory(
        "capability-method",
        module=__name__,
        qualname="_capability_program_factory",
    )
    builder.method_node(
        "run",
        definitions=("capability-method",),
    )
    return api.ResearchPortfolio("capability-suite", (builder.freeze(),))


def test_canonical_runtime_executes_method_and_evaluation_through_machine_journals(
    tmp_path: Path,
) -> None:
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
    values = ResearchOSValueRouter((_DataAuthority(),))
    research_os = bind_portfolio_research_os(
        revisions,
        blobs,
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            values,
        ),
    )
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="canonical runtime")
        receipt = research_os.run(
            api.ResearchExecutionTarget("canonical-execution", revision)
        )
        assert receipt.state == "succeeded"
        assert (tmp_path / "machine-state" / "program-journal" / "machines").is_dir()
        assert (tmp_path / "machine-state" / "method-state" / "journal").is_dir()
    finally:
        pool.close()


def test_canonical_runtime_rejects_missing_method_capability_inventory(
    tmp_path: Path,
) -> None:
    from noetrium_platform.composition.research_os_execution import (
        prepare_research_os_execution,
    )

    portfolio = _capability_portfolio()
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "missing method capability",
    )
    with pytest.raises(
        CanonicalResearchOSRuntimeUnsupported,
        match="canonical Method runtime binding is incomplete",
    ):
        prepare_research_os_execution(
            api.ResearchExecutionTarget("missing-capability", revision),
            portfolio,
            CanonicalResearchOSNodeRuntime(tmp_path / "machine-state"),
            ResearchOSValueRouter(()),
        )


def test_canonical_runtime_injects_explicit_method_capability_inventory(
    tmp_path: Path,
) -> None:
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    capability = _EchoCapability()
    runtime = CanonicalResearchOSNodeRuntime(
        tmp_path / "machine-state",
        method_runtime_inventory=MethodRuntimePortInventory(
            capabilities=capability,
        ),
    )
    research_os = bind_portfolio_research_os(
        revisions,
        blobs,
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            ResearchOSValueRouter(()),
        ),
    )
    try:
        portfolio = _capability_portfolio()
        revision = research_os.commit(portfolio, message="capability runtime")
        target = api.ResearchExecutionTarget("capability-runtime", revision)
        receipt = research_os.run(target)
        if receipt.state != "succeeded":
            print("CAPABILITY_FAILURE_INSPECT", research_os.inspect(target).payload)
            active = graph.active_cut(target.execution_id)
            if active is not None:
                print(
                    "CAPABILITY_FAILURE_NODE",
                    graph.node_state(active.cut_id, "capability-paper::run"),
                )
        assert receipt.state == "succeeded", receipt.payload
        assert capability.calls == 1
    finally:
        pool.close()


def test_canonical_runtime_checkpoint_binds_real_machine_journal_heads(
    tmp_path: Path,
) -> None:
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
    values = ResearchOSValueRouter((_DataAuthority(),))
    research_os = bind_portfolio_research_os(
        revisions,
        blobs,
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            values,
            checkpoints=DirectoryResearchOSGraphCheckpointStore(
                tmp_path / "graph-checkpoints"
            ),
        ),
    )
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="checkpoint proof")
        target = api.ResearchExecutionTarget("canonical-checkpoint", revision)
        assert research_os.run(target).state == "succeeded"
        checkpoint = research_os.checkpoint(target)
        assert checkpoint.state == "checkpointed"
        nodes = {
            row["graph_node_id"]: row
            for row in checkpoint.payload["checkpoint_nodes"]
        }
        assert set(nodes) == {"paper::source", "paper::evaluate"}
        for row in nodes.values():
            assert row["authority_id"] == "machine-journal"
            assert row["machine_revision"] >= 1
            assert len(row["machine_commit_id"]) == 64
            assert len(row["machine_cut_digest"]) == 64
            assert len(row["checkpoint_proof_digest"]) == 64

        restarted_store = DirectoryResearchOSGraphCheckpointStore(
            tmp_path / "graph-checkpoints"
        )
        durable = restarted_store.load(checkpoint.payload["checkpoint_digest"])
        assert durable is not None
        assert durable.checkpoint_digest == checkpoint.payload["checkpoint_digest"]
        assert durable.execution_cut_id == checkpoint.payload["cut_id"]
        assert durable.selected_node_ids == ("paper::evaluate", "paper::source")
        assert restarted_store.latest(
            durable.execution_cut_id,
            durable.selected_node_ids,
        ) == durable
    finally:
        pool.close()


def test_canonical_runtime_rejects_experiment_family_until_experiment_lowering_exists(
    tmp_path: Path,
) -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.benchmark("benchmark", implementation=_benchmark)
    builder.experiment("main", definitions=("benchmark",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "experiment must be canonical",
    )

    from noetrium_platform.composition.research_os_execution import (
        prepare_research_os_execution,
    )

    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
    with pytest.raises(
        ResearchOSExperimentClosureMissing,
        match="explicit canonical experiment closure provider",
    ):
        prepare_research_os_execution(
            api.ResearchExecutionTarget("experiment", revision),
            portfolio,
            runtime,
            ResearchOSValueRouter(()),
        )


def test_canonical_runtime_rejects_unresolved_platform_requirements(
    tmp_path: Path,
) -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.model("planner", config={"role": "planner"})
    builder.node(
        "run",
        kind=api.ResearchNodeKind.RUN,
        definitions=("planner",),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "requirements",
    )

    from noetrium_platform.composition.research_os_execution import (
        prepare_research_os_execution,
    )

    with pytest.raises(
        CanonicalResearchOSRuntimeUnsupported,
        match="unresolved platform requirements",
    ):
        prepare_research_os_execution(
            api.ResearchExecutionTarget("requirements", revision),
            portfolio,
            CanonicalResearchOSNodeRuntime(tmp_path / "machine-state"),
            ResearchOSValueRouter(()),
        )


def _migration_portfolio(source_impl) -> api.ResearchPortfolio:
    first = api.ResearchProgramBuilder("paper-a")
    first.method("source-method", implementation=source_impl)
    first.metric("metric", implementation=_metric)
    first.node(
        "source",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("source-method",),
        outputs=(api.ResearchOutputSpec("data", api.ResearchValueKind.DATA),),
    )
    first.evaluation(
        "evaluate",
        definitions=("metric",),
        outputs=(api.ResearchOutputSpec("result", api.ResearchValueKind.DATA),),
    )
    first.depends(
        "evaluate",
        "source",
        bindings=(
            api.ResearchInputBinding("source", "data", api.ResearchValueKind.DATA),
        ),
    )

    second = api.ResearchProgramBuilder("paper-b")
    second.method("stable-method", implementation=_stable)
    second.node(
        "stable",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("stable-method",),
        outputs=(api.ResearchOutputSpec("data", api.ResearchValueKind.DATA),),
    )
    return api.ResearchPortfolio("migration-suite", (first.freeze(), second.freeze()))


def test_live_revision_migration_reuses_only_proven_unchanged_nodes(
    tmp_path: Path,
) -> None:
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
    authority = _DataAuthority()
    research_os = bind_portfolio_research_os(
        revisions,
        blobs,
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            ResearchOSValueRouter((authority,)),
        ),
    )
    try:
        first_portfolio = _migration_portfolio(_source)
        first_revision = research_os.commit(first_portfolio, message="r1")
        first_target = api.ResearchExecutionTarget("live-migration", first_revision)
        assert research_os.run(first_target).state == "succeeded"
        assert research_os.pause(first_target).state == "paused"

        second_portfolio = _migration_portfolio(_source_v2)
        second_revision = research_os.commit(
            second_portfolio,
            parents=(first_revision,),
            message="r2",
        )
        second_target = api.ResearchExecutionTarget("live-migration", second_revision)
        migrated = research_os.migrate(second_target)
        assert migrated.state == "paused"
        assert tuple(migrated.payload["reused_node_ids"]) == ("paper-b::stable",)
        assert set(migrated.payload["restart_node_ids"]) == {
            "paper-a::source",
            "paper-a::evaluate",
        }

        resumed = research_os.resume(second_target)
        assert resumed.state == "succeeded"
        inspected = research_os.inspect(second_target)
        assert tuple(inspected.payload["states"]["reused"]) == ("paper-b::stable",)
        assert set(inspected.payload["states"]["succeeded"]) == {
            "paper-a::source",
            "paper-a::evaluate",
        }
    finally:
        pool.close()
