from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.product import research_os as research_os_api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import StrictResearchOSControl
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_runtime import (
    CanonicalResearchOSNodeRuntime,
)
from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSArtifactValueAuthority,
)
from noetrium_platform.composition.research_os_values import (
    ResearchOSValueRouter,
    ResearchOSValueSubject,
)
from noetrium_platform.evidence.artifact.catalog.providers import (
    SQLiteArtifactRegistry,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.evidence.artifact.contracts import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.lineage.relation.providers import (
    SQLiteArtifactLineageStore,
)
from noetrium_platform.evidence.artifact.retention.providers import (
    SQLiteArtifactRetentionStore,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _artifact_v1():
    return {"artifact": "changed-paper", "revision": 1}


def _artifact_v2():
    return {"artifact": "changed-paper", "revision": 2}


def _stable_artifact():
    return {"artifact": "stable-paper", "revision": 1}


def _portfolio(changed_impl) -> research_os_api.ResearchPortfolio:
    changed = research_os_api.ResearchProgramBuilder("paper-a")
    changed.method("artifact-method", implementation=changed_impl)
    changed.node(
        "source",
        kind=research_os_api.ResearchNodeKind.METHOD,
        definitions=("artifact-method",),
        outputs=(
            research_os_api.ResearchOutputSpec(
                "artifact",
                research_os_api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )

    stable = research_os_api.ResearchProgramBuilder("paper-b")
    stable.method("stable-method", implementation=_stable_artifact)
    stable.node(
        "stable",
        kind=research_os_api.ResearchNodeKind.METHOD,
        definitions=("stable-method",),
        outputs=(
            research_os_api.ResearchOutputSpec(
                "artifact",
                research_os_api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    return research_os_api.ResearchPortfolio(
        "artifact-migration-suite",
        (changed.freeze(), stable.freeze()),
    )


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def test_live_revision_migration_rebinds_artifact_and_records_reuse_lineage(
    tmp_path: Path,
) -> None:
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
    value_blobs = DirectoryArtifactBlobStore(tmp_path / "value-blobs")
    authority = ResearchOSArtifactValueAuthority(
        value_blobs,
        SQLiteArtifactRegistry(tmp_path / "artifact-catalog.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "artifact-retention.sqlite3"),
    )
    lineage = SQLiteArtifactLineageStore(tmp_path / "artifact-lineage.sqlite3")
    pool = _pool()
    research_os = bind_portfolio_research_os(
        revisions,
        DirectoryArtifactBlobStore(tmp_path / "portfolio-blobs"),
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            ResearchOSValueRouter((authority,)),
            artifact_lineage=lineage,
        ),
    )
    try:
        first_portfolio = _portfolio(_artifact_v1)
        first_revision = research_os.commit(first_portfolio, message="r1")
        first_target = research_os_api.ResearchExecutionTarget(
            "artifact-live-migration",
            first_revision,
        )
        assert research_os.run(first_target).state == "succeeded"
        assert research_os.pause(first_target).state == "paused"

        first_compilation = compile_research_portfolio_graph(
            first_revision,
            first_portfolio,
        )
        first_stable = first_compilation.node("paper-b::stable")
        source_cut = graph.active_cut(first_target.execution_id)
        assert source_cut is not None
        source_reference = authority.lookup(
            ResearchOSValueSubject(
                source_cut.cut_id,
                first_stable.graph_node_id,
                "artifact",
                research_os_api.ResearchValueKind.ARTIFACT,
                first_stable.semantic_digest,
            )
        )
        assert source_reference.content_digest is not None

        second_portfolio = _portfolio(_artifact_v2)
        second_revision = research_os.commit(
            second_portfolio,
            parents=(first_revision,),
            message="r2",
        )
        second_target = research_os_api.ResearchExecutionTarget(
            first_target.execution_id,
            second_revision,
        )
        migrated = research_os.migrate(second_target)

        assert migrated.state == "paused"
        assert migrated.payload["source_cut_id"] == source_cut.cut_id
        assert migrated.payload["reused_node_ids"] == ("paper-b::stable",)
        assert migrated.payload["restart_node_ids"] == ("paper-a::source",)

        second_compilation = compile_research_portfolio_graph(
            second_revision,
            second_portfolio,
        )
        second_stable = second_compilation.node("paper-b::stable")
        target_reference = authority.lookup(
            ResearchOSValueSubject(
                migrated.payload["target_cut_id"],
                second_stable.graph_node_id,
                "artifact",
                research_os_api.ResearchValueKind.ARTIFACT,
                second_stable.semantic_digest,
            )
        )
        assert target_reference.content_digest == source_reference.content_digest
        assert target_reference.authority_ref != source_reference.authority_ref
        assert authority.resolve(target_reference) == authority.resolve(source_reference)

        target_identity = ArtifactContentIdentity(
            target_reference.authority_ref,
            target_reference.content_digest or "",
        )
        reuse_edges = lineage.parents(target_identity)
        assert len(reuse_edges) == 1
        assert reuse_edges[0].relation_type == "reused_from"
        assert reuse_edges[0].parent == ArtifactContentIdentity(
            source_reference.authority_ref,
            source_reference.content_digest,
        )

        target_cut_id = migrated.payload["target_cut_id"]
        assert graph.attempts(target_cut_id, "paper-b::stable") == ()
        assert research_os.resume(second_target).state == "succeeded"
        assert graph.attempts(target_cut_id, "paper-b::stable") == ()
        assert len(graph.attempts(target_cut_id, "paper-a::source")) == 1
    finally:
        pool.close()
