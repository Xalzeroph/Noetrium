from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.evidence.artifact.catalog.api import ArtifactKind, ArtifactRecord
from noetrium_platform.evidence.artifact.catalog.runtime import InMemoryArtifactRegistry
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity, DatasetVersion
from noetrium_platform.evidence.data.dataset.runtime import InMemoryDatasetRegistry
from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchQueryGapKind,
    ResearchQuerySourceError,
    ResearchResultKind,
    ResearchResultQuery,
    ResearchSourceDisposition,
)
from noetrium_platform.evidence.data.query.cross.composition import (
    ArtifactCatalogResearchResultSource,
    compose,
)
from noetrium_platform.evidence.data.query.cross.providers import DatasetResearchResultSource
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scopes() -> tuple[InMemoryScopeRegistry, ScopeIdentity]:
    registry = InMemoryScopeRegistry()
    workspace = ScopeIdentity(ScopeKind.WORKSPACE, "workspace-a")
    program = ScopeIdentity(ScopeKind.PROGRAM, "program-a")
    project = ScopeIdentity(ScopeKind.PROJECT, "paper-a")
    study = ScopeIdentity(ScopeKind.STUDY, "study-a")
    experiment = ScopeIdentity(ScopeKind.EXPERIMENT, "experiment-a")
    run = ScopeIdentity(ScopeKind.RUN, "run-a")
    for child, parent in (
        (workspace, PLATFORM_SCOPE),
        (program, workspace),
        (project, program),
        (study, project),
        (experiment, study),
        (run, experiment),
    ):
        registry.register(child, parent)
    return registry, run


def _federation():
    scopes, run = _scopes()
    datasets = InMemoryDatasetRegistry()
    artifacts = InMemoryArtifactRegistry()
    datasets.register(
        DatasetVersion(
            DatasetIdentity("evaluation", "v1"),
            run,
            _sha("dataset-v1"),
            schema_ref="schema:evaluation.v1",
        )
    )
    artifacts.put(
        ArtifactRecord(
            artifact_id="report:summary",
            kind=ArtifactKind.REPORT,
            scope=run,
            digest=_sha("report-v1"),
            producer_component_id="project.analysis",
            media_type="application/json",
        )
    )
    sources = (
        DatasetResearchResultSource(datasets, scopes),
        ArtifactCatalogResearchResultSource(artifacts, scopes),
    )
    return compose(sources), datasets


def test_research_result_federation_queries_scientific_dimensions_and_pins_source_cuts() -> None:
    federation, _ = _federation()
    selector = ResearchDimension(ResearchDimensionKind.PROJECT, "paper-a")
    first = federation.query(
        ResearchResultQuery(
            dimensions=(selector,),
            kinds=(ResearchResultKind.DATASET, ResearchResultKind.REPORT),
            limit=100,
        )
    )
    assert first.complete is True
    assert first.truncated is False
    assert first.matched_count == 2
    assert first.gaps == ()
    assert len(first.records) == 2
    assert all(not hasattr(row, "location") for row in first.records)
    assert {row.reference.kind for row in first.records} == {
        ResearchResultKind.DATASET,
        ResearchResultKind.REPORT,
    }
    pinned = tuple(status.cut for status in first.sources if status.cut is not None)
    second = federation.query(
        ResearchResultQuery(
            dimensions=(selector,),
            kinds=(ResearchResultKind.DATASET, ResearchResultKind.REPORT),
            pinned_source_cuts=pinned,
            limit=1,
        )
    )
    assert second.complete is False
    assert second.truncated is True
    assert second.matched_count == 2
    assert second.query_digest == first.query_digest
    assert second.input_cut_digest == first.input_cut_digest
    assert len(second.records) == 1


def test_pinned_source_cut_rejects_new_data_instead_of_silently_mixing_generations() -> None:
    federation, datasets = _federation()
    query = ResearchResultQuery(kinds=(ResearchResultKind.DATASET,))
    first = federation.query(query)
    pinned = tuple(status.cut for status in first.sources if status.cut is not None)
    datasets.register(
        DatasetVersion(
            DatasetIdentity("evaluation", "v2"),
            first.records[0].scope,
            _sha("dataset-v2"),
            schema_ref="schema:evaluation.v1",
            parent_versions=(DatasetIdentity("evaluation", "v1"),),
        )
    )
    stale = federation.query(
        ResearchResultQuery(
            kinds=(ResearchResultKind.DATASET,),
            pinned_source_cuts=pinned,
        )
    )
    assert stale.complete is False
    assert stale.input_cut_digest != first.input_cut_digest
    dataset_status = next(row for row in stale.sources if row.source_id == "data.dataset")
    assert dataset_status.disposition is ResearchSourceDisposition.STALE
    assert dataset_status.diagnostic_code == "PINNED_CUT_MISMATCH"
    assert all(row.reference.source_authority != "data.dataset" for row in stale.records)


def test_missing_measurement_source_is_an_explicit_gap_not_a_complete_empty_result() -> None:
    federation, _ = _federation()
    page = federation.query(ResearchResultQuery(kinds=(ResearchResultKind.MEASUREMENT,)))
    assert page.complete is False
    assert page.records == ()
    assert page.gaps == (
        pytest.helpers.anything if False else page.gaps[0],
    )
    gap = page.gaps[0]
    assert gap.kind is ResearchQueryGapKind.RESULT_KIND
    assert gap.value == ResearchResultKind.MEASUREMENT.value
    assert gap.diagnostic_code == "NO_SOURCE_CAPABILITY"


def test_query_federation_propagates_untyped_programming_failures() -> None:
    class BrokenSource:
        source_id = "broken.source"
        supported_kinds = frozenset({ResearchResultKind.ARTIFACT})
        supported_dimensions = frozenset()

        def snapshot(self, query):
            del query
            raise RuntimeError("programming bug")

    federation = compose((BrokenSource(),))
    with pytest.raises(RuntimeError, match="programming bug"):
        federation.query()

def test_typed_source_failure_is_reported_as_incomplete_without_becoming_authority() -> None:
    class IncompleteSource:
        source_id = "incomplete.source"
        supported_kinds = frozenset({ResearchResultKind.ARTIFACT})
        supported_dimensions = frozenset()

        def snapshot(self, query):
            del query
            raise ResearchQuerySourceError(
                self.source_id,
                "INDEX_REBUILDING",
                "projection is not ready",
                disposition=ResearchSourceDisposition.INCOMPLETE,
            )

    page = compose((IncompleteSource(),)).query(
        ResearchResultQuery(kinds=(ResearchResultKind.ARTIFACT,))
    )
    assert page.complete is False
    assert page.records == ()
    assert page.sources[0].disposition is ResearchSourceDisposition.INCOMPLETE
    assert page.sources[0].diagnostic_code == "INDEX_REBUILDING"


def test_query_cross_no_longer_exposes_generic_execute_or_checkpoint_authority() -> None:
    federation, _ = _federation()
    assert not hasattr(federation, "execute")
    assert not hasattr(federation, "checkpoint")
    assert not hasattr(federation, "restore")
    assert not hasattr(federation, "read_state")
