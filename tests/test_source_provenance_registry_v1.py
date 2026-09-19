from __future__ import annotations

import pytest

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def test_candidate_and_classified_sources_share_one_registry_and_digest_path() -> None:
    candidate = MethodSourceLane(
        lane_id="candidate_unclassified_01",
        kind=MethodSourceLaneKind.CANDIDATE,
        repository="https://github.com/example/candidate",
        commit=COMMIT_A,
        artifacts=(),
    )
    official = MethodSourceLane(
        lane_id="paper_release",
        kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
        repository="https://github.com/example/official",
        commit=COMMIT_B,
        artifacts=("run.py",),
    )

    registry = MethodSourceRegistry(lanes=(official, candidate))

    assert tuple(row.lane_id for row in registry.lanes) == (
        "candidate_unclassified_01",
        "paper_release",
    )
    assert candidate.executable is False
    assert official.executable is True
    assert registry.repositories == (
        "https://github.com/example/candidate",
        "https://github.com/example/official",
    )
    assert len(registry.registry_digest) == 64


def test_classified_source_lane_requires_at_least_one_artifact() -> None:
    with pytest.raises(ValueError, match="at least one source artifact"):
        MethodSourceLane(
            lane_id="paper_release",
            kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
            repository="https://github.com/example/official",
            commit=COMMIT_A,
            artifacts=(),
        )


def test_source_registry_rejects_duplicate_lane_identity() -> None:
    lane = MethodSourceLane(
        lane_id="candidate_unclassified_01",
        kind=MethodSourceLaneKind.CANDIDATE,
        repository="https://github.com/example/candidate",
        commit=COMMIT_A,
        artifacts=(),
    )
    with pytest.raises(ValueError, match="lane identities must be unique"):
        MethodSourceRegistry(lanes=(lane, lane))


def test_publication_source_lane_does_not_fake_git_provenance() -> None:
    publication = PublicationSourceLane(
        lane_id="neurips_2022_paper",
        venue="NeurIPS",
        year=2022,
        publication_id="9d5609613524ecf4f15af0f7b31abca4",
        publication_uri=(
            "https://proceedings.neurips.cc/paper/2022/hash/"
            "9d5609613524ecf4f15af0f7b31abca4-Abstract-Conference.html"
        ),
        revision="final",
    )
    registry = MethodSourceRegistry(lanes=(publication,))

    assert publication.kind is MethodSourceLaneKind.PAPER_PROVENANCE
    assert publication.executable is False
    assert registry.repositories == ()
    assert registry.publication_uris == (publication.publication_uri,)
    assert len(publication.lane_digest) == 64


def test_publication_source_lane_validates_optional_content_digest() -> None:
    with pytest.raises(ValueError, match="content_sha256"):
        PublicationSourceLane(
            lane_id="iclr_paper",
            venue="ICLR",
            year=2023,
            publication_id="1PL1NIMMrw",
            publication_uri="https://openreview.net/forum?id=1PL1NIMMrw",
            content_sha256="not-a-digest",
        )
