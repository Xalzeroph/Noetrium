from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)
from research.reproductions.benchmark_authority import (
    RepositoryBenchmarkAuthority,
    RepositoryBenchmarkBinding,
)
from research.reproductions.research_os import (
    ReproductionResearchOSCompileError,
    resolve_study_factory_bindings,
)
from research.reproductions.storm_wiki.definition import (
    REPRODUCTION as STORM,
)
from research.reproductions.vima_embodied.definition import (
    REPRODUCTION as VIMA,
)


def test_repository_authority_discovers_source_contained_vima_cut() -> None:
    authority = RepositoryBenchmarkAuthority.discover()
    matches = tuple(
        row for row in authority.bindings if row.benchmark_id == "vima-bench"
    )
    assert len(matches) == 1
    binding = matches[0]
    assert binding.resolution.task_set.benchmark_id == "vima-bench"
    assert len(binding.source_sha256) == 64
    assert len(binding.binding_digest) == 64

    study = resolve_study_factory_bindings(VIMA)
    assert len(study) == 1
    selections = authority.resolve(VIMA, study[0])
    assert len(selections) == 1
    assert selections[0].benchmark.benchmark_id == "vima-bench"
    assert selections[0].benchmark_split_ids == ()
    assert len(selections[0].resolution_proof_digest) == 64


def test_repository_authority_never_promotes_external_materialization_to_exact_cut() -> None:
    authority = RepositoryBenchmarkAuthority.discover()
    assert "alfworld" not in authority.benchmark_ids


def _freshwiki_resolution() -> BenchmarkSourceResolution:
    source_digest = canonical_digest({"fixture": "freshwiki"})
    revision = "fixture:freshwiki"
    source = BenchmarkSourceSpec(
        source_id="freshwiki",
        kind=BenchmarkSourceKind.HTTP,
        revision_id=revision,
        locator="https://example.invalid/freshwiki",
        content_digest=source_digest,
    )
    tasks = (
        TaskDefinition(
            "dev-task",
            revision,
            "wiki",
            "freshwiki.fixture.v1",
            canonical_digest({"task": "dev"}),
        ),
        TaskDefinition(
            "test-task",
            revision,
            "wiki",
            "freshwiki.fixture.v1",
            canonical_digest({"task": "test"}),
        ),
    )
    task_set = BenchmarkTaskSet(
        benchmark_id="freshwiki",
        revision_id=revision,
        source_digest=source_digest,
        task_schema_id="freshwiki.fixture.v1",
        tasks=tasks,
        splits=(
            TaskSetSplit("dev", ("dev-task",)),
            TaskSetSplit("test", ("test-task",)),
        ),
    )
    return BenchmarkSourceResolution(source, task_set)


def test_repository_authority_fails_closed_on_ambiguous_paper_split() -> None:
    resolution = _freshwiki_resolution()
    authority = RepositoryBenchmarkAuthority(
        (
            RepositoryBenchmarkBinding(
                "fixture",
                __name__,
                "_freshwiki_resolution",
                "a" * 64,
                resolution,
            ),
        )
    )
    study = resolve_study_factory_bindings(STORM)
    assert len(study) == 1

    with pytest.raises(
        ReproductionResearchOSCompileError,
        match="requires paper-owned split selection",
    ):
        authority.resolve(STORM, study[0])
