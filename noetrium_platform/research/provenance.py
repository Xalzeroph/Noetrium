"""Canonical immutable source provenance for research methods and artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re

from noetrium_platform.foundation.kernel.kernel import canonical_digest

_HEX = frozenset("0123456789abcdef")
_SOURCE_LANE_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class MethodSourceLaneKind(StrEnum):
    """Scientific relationship between a method claim and one immutable source cut."""

    OFFICIAL_EXECUTABLE = "official_executable"
    LATER_RELEASED_EXECUTABLE = "later_released_executable"
    OFFICIAL_ARTIFACT = "official_artifact"
    SURROGATE = "surrogate"
    INDEPENDENT = "independent"
    PAPER_PROVENANCE = "paper_provenance"
    CANDIDATE = "candidate"

    @property
    def executable(self) -> bool:
        return self in {
            MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
            MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
            MethodSourceLaneKind.SURROGATE,
            MethodSourceLaneKind.INDEPENDENT,
        }


@dataclass(frozen=True, slots=True)
class MethodSourceLane:
    """Immutable source-lane identity shared by Study and reproduction governance.

    Mutable branch/tag names are deliberately excluded. Scientific identity is
    the lane relation, HTTPS repository, full Git commit and repository-relative
    source artifacts.
    """

    lane_id: str
    kind: MethodSourceLaneKind
    repository: str
    commit: str
    artifacts: tuple[str, ...]
    lane_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.lane_id, "method source lane lane_id")
        if _SOURCE_LANE_TOKEN.fullmatch(self.lane_id) is None:
            raise ValueError("method source lane lane_id must be a canonical token")
        if not isinstance(self.kind, MethodSourceLaneKind):
            raise TypeError("method source lane kind must be MethodSourceLaneKind")
        repository = _text(self.repository, "method source lane repository")
        if not repository.startswith("https://"):
            raise ValueError("method source lane repository must be an HTTPS URI")
        commit = _text(self.commit, "method source lane commit")
        if len(commit) != 40 or any(ch not in _HEX for ch in commit):
            raise ValueError("method source lane commit must be a full lowercase Git SHA")
        if type(self.artifacts) is not tuple:
            raise TypeError("method source lane artifacts must be a tuple")
        if not self.artifacts and self.kind is not MethodSourceLaneKind.CANDIDATE:
            raise ValueError("classified method source lanes must name at least one source artifact")
        normalized: list[str] = []
        for artifact in self.artifacts:
            path = _text(artifact, "method source lane artifact")
            if (
                "\\" in path
                or path.startswith("/")
                or path == ".."
                or path.startswith("../")
                or "/../" in path
            ):
                raise ValueError(
                    "method source lane artifact must be a repository-relative POSIX path"
                )
            normalized.append(path)
        ordered = tuple(sorted(normalized))
        if len(ordered) != len(set(ordered)):
            raise ValueError("method source lane artifacts must be unique")
        object.__setattr__(self, "artifacts", ordered)
        object.__setattr__(
            self,
            "lane_digest",
            canonical_digest(
                {
                    "lane_id": self.lane_id,
                    "kind": self.kind.value,
                    "repository": self.repository,
                    "commit": self.commit,
                    "artifacts": self.artifacts,
                }
            ),
        )

    @property
    def executable(self) -> bool:
        return self.kind.executable


@dataclass(frozen=True, slots=True)
class PublicationSourceLane:
    """Immutable venue-assigned paper provenance, independent of executable code.

    A publication lane proves which peer-reviewed document defines the method.
    It deliberately does not pretend that a paper has a Git commit. Venue/year/
    publication_id plus the canonical HTTPS URI are mandatory; a byte-level
    SHA-256 may be attached when the final publication artifact is available as
    stable raw bytes.
    """

    lane_id: str
    venue: str
    year: int
    publication_id: str
    publication_uri: str
    revision: str | None = None
    content_sha256: str | None = None
    kind: MethodSourceLaneKind = field(
        default=MethodSourceLaneKind.PAPER_PROVENANCE,
        init=False,
    )
    lane_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.lane_id, "publication source lane lane_id")
        if _SOURCE_LANE_TOKEN.fullmatch(self.lane_id) is None:
            raise ValueError("publication source lane lane_id must be a canonical token")
        _text(self.venue, "publication source lane venue")
        if type(self.year) is not int or not 1900 <= self.year <= 2200:
            raise ValueError("publication source lane year is invalid")
        _text(self.publication_id, "publication source lane publication_id")
        uri = _text(self.publication_uri, "publication source lane publication_uri")
        if not uri.startswith("https://"):
            raise ValueError("publication source lane publication_uri must be HTTPS")
        if self.revision is not None:
            _text(self.revision, "publication source lane revision")
        if self.content_sha256 is not None:
            digest = self.content_sha256
            if (
                type(digest) is not str
                or digest != digest.lower()
                or len(digest) != 64
                or any(ch not in _HEX for ch in digest)
            ):
                raise ValueError(
                    "publication source lane content_sha256 must be canonical SHA-256"
                )
        object.__setattr__(
            self,
            "lane_digest",
            canonical_digest(
                {
                    "lane_id": self.lane_id,
                    "kind": self.kind.value,
                    "venue": self.venue,
                    "year": self.year,
                    "publication_id": self.publication_id,
                    "publication_uri": self.publication_uri,
                    "revision": self.revision,
                    "content_sha256": self.content_sha256,
                }
            ),
        )

    @property
    def executable(self) -> bool:
        return False


SourceLane = MethodSourceLane | PublicationSourceLane


@dataclass(frozen=True, slots=True)
class MethodSourceRegistry:
    """One canonical registry for every immutable method-source cut.

    Candidate discovery cuts and scientifically classified source lanes share the
    same identity, validation, and digest path. Classification is expressed only
    by MethodSourceLane.kind; there is no parallel candidate entity.
    """

    lanes: tuple[SourceLane, ...] = ()
    registry_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.lanes) is not tuple or any(
            type(row) not in {MethodSourceLane, PublicationSourceLane}
            for row in self.lanes
        ):
            raise TypeError(
                "method source registry lanes must be MethodSourceLane or PublicationSourceLane"
            )
        lanes = tuple(sorted(self.lanes, key=lambda row: row.lane_id))
        object.__setattr__(self, "lanes", lanes)
        lane_ids = tuple(row.lane_id for row in lanes)
        if len(lane_ids) != len(set(lane_ids)):
            raise ValueError("method source registry lane identities must be unique")
        object.__setattr__(
            self,
            "registry_digest",
            canonical_digest({"lanes": tuple(row.lane_digest for row in lanes)}),
        )

    @property
    def repositories(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    row.repository
                    for row in self.lanes
                    if type(row) is MethodSourceLane
                }
            )
        )

    @property
    def publication_uris(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    row.publication_uri
                    for row in self.lanes
                    if type(row) is PublicationSourceLane
                }
            )
        )


__all__ = [
    "MethodSourceLane",
    "MethodSourceLaneKind",
    "MethodSourceRegistry",
    "PublicationSourceLane",
    "SourceLane",
]
