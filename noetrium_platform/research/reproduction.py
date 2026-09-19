"""Typed canonical declaration contracts for research reproductions.

Handwritten authority is split by concern:
- definition.py owns paper/catalog/lifecycle/claim metadata.
- source.py owns immutable method-source provenance.
- Study/Benchmark/Measurement/MethodProgram/ResearchProgram/Fidelity own executable science.
- reproduction.json is generated projection only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonObject, canonical_digest, freeze_json
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _token(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if _TOKEN.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a canonical token")
    return text


def _strings(value: object, field_name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    if any(type(row) is not str or not row.strip() or row != row.strip() for row in value):
        raise TypeError(f"{field_name} must contain canonical non-empty strings")
    if non_empty and not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value) != len(set(value)):
        raise ValueError(f"{field_name} must be unique")
    return value


class ReproductionLifecycle(StrEnum):
    CATALOGUED = "catalogued"
    PROTOCOL_BOUND = "protocol_bound"
    RUNNABLE = "runnable"
    PILOT = "pilot"
    MATCHED_REPRODUCTION = "matched_reproduction"
    BLOCKED = "blocked"
    PAPER_ONLY = "paper_only"
    ARTIFACT_ONLY = "artifact_only"


class ReproductionAssetKind(StrEnum):
    FIDELITY = "fidelity"
    STUDY = "study"
    BENCHMARK = "benchmark"
    METHOD_PROGRAM = "method_program"
    RESEARCH_PROGRAM = "research_program"
    SEMANTICS = "semantics"
    SUPPORT = "support"


class ReproductionDeltaKind(StrEnum):
    SUBSTITUTION = "substitution"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class ReproductionIdentity:
    method_id: str
    title: str
    paper_uri: str
    year: int
    paper_revision: str | None = None
    identity_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.method_id, "reproduction method_id")
        _text(self.title, "reproduction title")
        uri = _text(self.paper_uri, "reproduction paper_uri")
        if not uri.startswith("https://"):
            raise ValueError("reproduction paper_uri must be HTTPS")
        if type(self.year) is not int or not 1950 <= self.year <= 2100:
            raise ValueError("reproduction year is invalid")
        if self.paper_revision is not None:
            _text(self.paper_revision, "reproduction paper_revision")
        object.__setattr__(
            self,
            "identity_digest",
            canonical_digest(
                {
                    "method_id": self.method_id,
                    "title": self.title,
                    "paper_uri": self.paper_uri,
                    "year": self.year,
                    "paper_revision": self.paper_revision,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionCatalog:
    domains: tuple[str, ...]
    families: tuple[str, ...]
    priority: int
    benchmark_ids: tuple[str, ...]
    platform_pressure: tuple[str, ...]
    method_owned: tuple[str, ...]
    platform_owned: tuple[str, ...]
    catalog_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "domains",
            "families",
            "benchmark_ids",
            "platform_pressure",
            "method_owned",
            "platform_owned",
        ):
            value = _strings(
                getattr(self, field_name),
                f"reproduction catalog {field_name}",
                non_empty=field_name != "benchmark_ids",
            )
            object.__setattr__(self, field_name, tuple(sorted(value)))
        if type(self.priority) is not int or self.priority <= 0:
            raise ValueError("reproduction catalog priority must be positive")
        object.__setattr__(
            self,
            "catalog_digest",
            canonical_digest(
                {
                    "domains": self.domains,
                    "families": self.families,
                    "priority": self.priority,
                    "benchmark_ids": self.benchmark_ids,
                    "platform_pressure": self.platform_pressure,
                    "method_owned": self.method_owned,
                    "platform_owned": self.platform_owned,
                }
            ),
        )



@dataclass(frozen=True, slots=True)
class ReproductionAssetRef:
    kind: ReproductionAssetKind
    path: str
    declaration_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReproductionAssetKind):
            raise TypeError("reproduction asset kind must be ReproductionAssetKind")
        path = _text(self.path, "reproduction asset path")
        if "\\" in path or path.startswith("/") or path.startswith("../") or "/../" in path:
            raise ValueError("reproduction asset path must be repository-relative POSIX")
        object.__setattr__(
            self,
            "declaration_digest",
            canonical_digest({"kind": self.kind.value, "path": path}),
        )


@dataclass(frozen=True, slots=True)
class ReportedResult:
    claim_id: str
    metric_id: str
    value: int | float
    qualifiers: JsonObject = field(default_factory=dict)
    claim_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.claim_id, "reported result claim_id")
        _token(self.metric_id, "reported result metric_id")
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise TypeError("reported result value must be numeric")
        qualifiers = freeze_json(self.qualifiers)
        if not isinstance(qualifiers, Mapping):
            raise TypeError("reported result qualifiers must be a JSON object")
        object.__setattr__(self, "qualifiers", qualifiers)
        object.__setattr__(
            self,
            "claim_digest",
            canonical_digest(
                {
                    "claim_id": self.claim_id,
                    "metric_id": self.metric_id,
                    "value": self.value,
                    "qualifiers": qualifiers,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReferenceBaseline:
    baseline_id: str
    description: str
    qualifiers: JsonObject = field(default_factory=dict)
    baseline_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.baseline_id, "reference baseline id")
        _text(self.description, "reference baseline description")
        qualifiers = freeze_json(self.qualifiers)
        if not isinstance(qualifiers, Mapping):
            raise TypeError("reference baseline qualifiers must be a JSON object")
        object.__setattr__(self, "qualifiers", qualifiers)
        object.__setattr__(
            self,
            "baseline_digest",
            canonical_digest(
                {
                    "baseline_id": self.baseline_id,
                    "description": self.description,
                    "qualifiers": qualifiers,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionDelta:
    kind: ReproductionDeltaKind
    description: str
    delta_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReproductionDeltaKind):
            raise TypeError("reproduction delta kind must be ReproductionDeltaKind")
        _text(self.description, "reproduction delta description")
        object.__setattr__(
            self,
            "delta_digest",
            canonical_digest({"kind": self.kind.value, "description": self.description}),
        )


@dataclass(frozen=True, slots=True)
class ReproductionDefinition:
    package: str
    lifecycle: ReproductionLifecycle
    identity: ReproductionIdentity
    catalog: ReproductionCatalog
    assets: tuple[ReproductionAssetRef, ...]
    primary_executable: str | None = None
    reported_results: tuple[ReportedResult, ...] = ()
    reference_baselines: tuple[ReferenceBaseline, ...] = ()
    deltas: tuple[ReproductionDelta, ...] = ()
    blockers: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    scientific_tests: tuple[str, ...] = ()
    definition_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.package, "reproduction package")
        if not isinstance(self.lifecycle, ReproductionLifecycle):
            raise TypeError("reproduction lifecycle must be ReproductionLifecycle")
        if type(self.identity) is not ReproductionIdentity:
            raise TypeError("reproduction identity must be ReproductionIdentity")
        if type(self.catalog) is not ReproductionCatalog:
            raise TypeError("reproduction catalog must be ReproductionCatalog")
        if type(self.assets) is not tuple or not self.assets:
            raise TypeError("reproduction assets must be a non-empty tuple")
        if any(type(row) is not ReproductionAssetRef for row in self.assets):
            raise TypeError("reproduction assets must contain ReproductionAssetRef")
        assets = tuple(sorted(self.assets, key=lambda row: (row.kind.value, row.path)))
        object.__setattr__(self, "assets", assets)
        if len({row.path for row in assets}) != len(assets):
            raise ValueError("reproduction asset paths must be unique")
        executable_assets = tuple(
            row
            for row in assets
            if row.kind
            in {
                ReproductionAssetKind.METHOD_PROGRAM,
                ReproductionAssetKind.RESEARCH_PROGRAM,
            }
        )
        primary_executable = self.primary_executable
        if primary_executable is None and len(executable_assets) == 1:
            primary_executable = executable_assets[0].path
        if primary_executable is not None:
            primary_executable = _text(
                primary_executable,
                "reproduction primary_executable",
            )
            if not any(
                row.path == primary_executable
                for row in executable_assets
            ):
                raise ValueError(
                    "reproduction primary_executable must reference an "
                    "executable asset path"
                )
        object.__setattr__(
            self,
            "primary_executable",
            primary_executable,
        )
        for name, value, row_type, key in (
            ("reported_results", self.reported_results, ReportedResult, lambda row: row.claim_id),
            ("reference_baselines", self.reference_baselines, ReferenceBaseline, lambda row: row.baseline_id),
            ("deltas", self.deltas, ReproductionDelta, lambda row: row.delta_digest),
        ):
            if type(value) is not tuple or any(type(row) is not row_type for row in value):
                raise TypeError(f"reproduction {name} must contain typed values")
            identities = tuple(key(row) for row in value)
            if len(identities) != len(set(identities)):
                raise ValueError(f"reproduction {name} identities must be unique")
        blockers = _strings(self.blockers, "reproduction blockers")
        evidence_refs = _strings(self.evidence_refs, "reproduction evidence_refs")
        scientific_tests = _strings(
            self.scientific_tests,
            "reproduction scientific_tests",
            non_empty=True,
        )
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "scientific_tests", tuple(sorted(scientific_tests)))
        object.__setattr__(
            self,
            "definition_digest",
            canonical_digest(
                {
                    "package": self.package,
                    "lifecycle": self.lifecycle.value,
                    "identity": self.identity.identity_digest,
                    "catalog": self.catalog.catalog_digest,
                    "assets": tuple(row.declaration_digest for row in assets),
                    "primary_executable": primary_executable,
                    "reported_results": tuple(row.claim_digest for row in self.reported_results),
                    "reference_baselines": tuple(
                        row.baseline_digest for row in self.reference_baselines
                    ),
                    "deltas": tuple(row.delta_digest for row in self.deltas),
                    "blockers": blockers,
                    "evidence_refs": evidence_refs,
                    "scientific_tests": self.scientific_tests,
                }
            ),
        )


__all__ = [
    "ReferenceBaseline",
    "ReportedResult",
    "ReproductionAssetKind",
    "ReproductionAssetRef",
    "ReproductionCatalog",
    "ReproductionDefinition",
    "ReproductionDelta",
    "ReproductionDeltaKind",
    "ReproductionIdentity",
    "ReproductionLifecycle",
]
