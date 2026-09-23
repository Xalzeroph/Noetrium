from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_lowering import (
    compile_research_os_lowering,
)
from noetrium_platform.composition.research_os_migration import (
    ResearchOSExecutionCut,
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
    ExecutionContext,
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphReconciliationDisposition,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


_COUNTED_SOURCE_CALLS: list[int] = []


def _source():
    return {"value": 7}


def _counted_source():
    _COUNTED_SOURCE_CALLS.append(1)
    return {"value": 7}


def _boom():
    raise RuntimeError("boom")


def _metric(payload):
    return {"score": payload["source"]["value"] + 1}


def _benchmark():
    return ("task",)


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


def _counting_portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("source-method", implementation=_counted_source)
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
    return api.ResearchPortfolio("counting-suite", (builder.freeze(),))


def _failed_method_portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("boom-method", implementation=_boom)
    builder.node(
        "source",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("boom-method",),
    )
    return api.ResearchPortfolio("failed-suite", (builder.freeze(),))


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


def test_completed_lower_method_reconciles_by_replaying_publication_closure(
    tmp_path: Path,
) -> None:
    _COUNTED_SOURCE_CALLS.clear()
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
    authority = _DataAuthority()
    values = ResearchOSValueRouter((authority,))
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
        portfolio = _counting_portfolio()
        revision = research_os.commit(portfolio, message="reconcile publication")
        target = api.ResearchExecutionTarget("canonical-reconcile", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        lowering = compile_research_os_lowering(compilation)
        cut = ResearchOSExecutionCut.from_compilation(
            target.execution_id,
            compilation,
        )
        source = compilation.node("paper::source")
        source_lowering = lowering.node("paper::source")

        lower_value = runtime.execute(
            ExecutionContext("manual", "trace", "span"),
            source,
            source_lowering,
            {},
            execution_cut_id=cut.cut_id,
            deadline=None,
        )
        assert lower_value == {"value": 7}
        assert len(_COUNTED_SOURCE_CALLS) == 1

        graph.ensure_execution(cut.cut_id, compilation.plan)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        claimed = graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="worker-a",
            now_ns=2,
            lease_expires_at_ns=100,
        )
        assert claimed.attempt_id is not None
        graph.mark_running(
            cut.cut_id,
            "paper::source",
            attempt_id=claimed.attempt_id,
            owner_id="worker-a",
            now_ns=3,
        )

        research_os.interrupt(target)
        reconciled = research_os.reconcile(
            target.for_node("paper", "source")
        )
        assert reconciled.state == "paused"
        assert reconciled.payload["reconciliation_disposition"] == "retry"

        resumed = research_os.resume(target)
        assert resumed.state == "succeeded"
        assert len(_COUNTED_SOURCE_CALLS) == 1
        assert authority.rows
    finally:
        pool.close()


def test_failed_lower_method_produces_definitive_failed_reconciliation_proof(
    tmp_path: Path,
) -> None:
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
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
        portfolio = _failed_method_portfolio()
        revision = research_os.commit(portfolio, message="failed lower machine")
        target = api.ResearchExecutionTarget("canonical-failed", revision)
        receipt = research_os.run(target)
        assert receipt.state == "failed"

        compilation = compile_research_portfolio_graph(revision, portfolio)
        lowering = compile_research_os_lowering(compilation)
        active = graph.active_cut(target.execution_id)
        assert active is not None
        proof = runtime.reconcile(
            compilation.node("paper::source"),
            lowering.node("paper::source"),
            execution_cut_id=active.cut_id,
            attempt_id="synthetic-outer-attempt",
        )
        assert proof.disposition is ResearchGraphReconciliationDisposition.FAILED
        assert proof.failure_type == "LowerMachineFailed"
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
