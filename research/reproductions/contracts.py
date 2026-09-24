"""Research-workspace declaration contracts for repository reproductions.

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

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest, freeze_json
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _token(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if _TOKEN.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a canonical token")
    return text


def _sha256(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256")
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

@dataclass(frozen=True, slots=True)
class ReproductionMethodProgramFactoryBinding:
    """Explicit package-local MethodProgram factory identity.

    ``unresolved_parameters`` is not a fallback. It records parameters whose
    values belong to benchmark/Experimentation binding rather than the paper
    declaration. Such bindings may enter Research OS as protocol-bound metadata
    but cannot lower directly to UMM until an exact ExperimentClosure supplies
    those values.
    """

    qualname: str
    args: tuple[JsonValue, ...] = ()
    kwargs: JsonObject = field(default_factory=dict)
    unresolved_parameters: tuple[str, ...] = ()
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        qualname = _text(
            self.qualname,
            "reproduction MethodProgram factory qualname",
        )
        if "<locals>" in qualname or "<lambda>" in qualname:
            raise ValueError(
                "reproduction MethodProgram factory must be module-resolvable"
            )
        if type(self.args) is not tuple:
            raise TypeError(
                "reproduction MethodProgram factory args must be a tuple"
            )
        frozen_args = freeze_json(self.args)
        if type(frozen_args) is not tuple:
            raise TypeError(
                "reproduction MethodProgram factory args must freeze to tuple"
            )
        frozen_kwargs = freeze_json(self.kwargs)
        if not isinstance(frozen_kwargs, Mapping):
            raise TypeError(
                "reproduction MethodProgram factory kwargs must be a JSON object"
            )
        unresolved = tuple(
            sorted(
                _strings(
                    self.unresolved_parameters,
                    "reproduction MethodProgram factory unresolved_parameters",
                )
            )
        )
        overlap = set(unresolved) & set(frozen_kwargs)
        if overlap:
            raise ValueError(
                "reproduction MethodProgram factory parameters cannot be both "
                f"bound and unresolved: {tuple(sorted(overlap))}"
            )
        object.__setattr__(self, "qualname", qualname)
        object.__setattr__(self, "args", frozen_args)
        object.__setattr__(self, "kwargs", frozen_kwargs)
        object.__setattr__(self, "unresolved_parameters", unresolved)
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "qualname": qualname,
                    "args": frozen_args,
                    "kwargs": frozen_kwargs,
                    "unresolved_parameters": unresolved,
                }
            ),
        )

    @property
    def exact(self) -> bool:
        return not self.unresolved_parameters


class ReproductionDeltaKind(StrEnum):
    SUBSTITUTION = "substitution"
    UNRESOLVED = "unresolved"


class ReproductionEvidenceKind(StrEnum):
    PILOT = "pilot"
    MATCHED_RESULT = "matched_result"


class ReproductionMatchCriterionStatus(StrEnum):
    SATISFIED = "satisfied"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


REPRODUCTION_MATCH_REQUIRED_CRITERIA = (
    "benchmark-cut",
    "method-semantics",
    "model-identity",
    "environment",
    "evaluation-protocol",
)


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
class ReproductionMatchCriterion:
    criterion_id: str
    status: ReproductionMatchCriterionStatus
    authority_digest: str
    detail: str
    criterion_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.criterion_id, "reproduction match criterion_id")
        if not isinstance(self.status, ReproductionMatchCriterionStatus):
            raise TypeError(
                "reproduction match criterion status must be "
                "ReproductionMatchCriterionStatus"
            )
        _sha256(
            self.authority_digest,
            "reproduction match criterion authority_digest",
        )
        _text(self.detail, "reproduction match criterion detail")
        object.__setattr__(
            self,
            "criterion_digest",
            canonical_digest(
                {
                    "criterion_id": self.criterion_id,
                    "status": self.status.value,
                    "authority_digest": self.authority_digest,
                    "detail": self.detail,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionEvidenceQualification:
    qualification_id: str
    decision: ReproductionEvidenceKind
    run_id: str
    run_manifest_digest: str
    evidence_bundle_digest: str
    claim_ids: tuple[str, ...]
    criteria: tuple[ReproductionMatchCriterion, ...]
    qualification_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(
            self.qualification_id,
            "reproduction evidence qualification_id",
        )
        if not isinstance(self.decision, ReproductionEvidenceKind):
            raise TypeError(
                "reproduction evidence qualification decision must be "
                "ReproductionEvidenceKind"
            )
        _text(self.run_id, "reproduction evidence qualification run_id")
        _sha256(
            self.run_manifest_digest,
            "reproduction evidence qualification run_manifest_digest",
        )
        _sha256(
            self.evidence_bundle_digest,
            "reproduction evidence qualification bundle digest",
        )
        claim_ids = tuple(
            sorted(
                _strings(
                    self.claim_ids,
                    "reproduction evidence qualification claim_ids",
                    non_empty=(
                        self.decision
                        is ReproductionEvidenceKind.MATCHED_RESULT
                    ),
                )
            )
        )
        for claim_id in claim_ids:
            _token(
                claim_id,
                "reproduction evidence qualification claim_id",
            )
        criteria = self.criteria
        if type(criteria) is not tuple or not criteria or any(
            type(row) is not ReproductionMatchCriterion
            for row in criteria
        ):
            raise TypeError(
                "reproduction evidence qualification criteria must contain "
                "at least one ReproductionMatchCriterion"
            )
        criteria = tuple(
            sorted(criteria, key=lambda row: row.criterion_id)
        )
        criterion_ids = tuple(row.criterion_id for row in criteria)
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError(
                "reproduction evidence qualification criteria must be unique"
            )
        if self.decision is ReproductionEvidenceKind.MATCHED_RESULT:
            missing = tuple(
                criterion_id
                for criterion_id in REPRODUCTION_MATCH_REQUIRED_CRITERIA
                if criterion_id not in criterion_ids
            )
            if missing:
                raise ValueError(
                    "matched-result qualification is missing required criteria: "
                    + ", ".join(missing)
                )
            unresolved = tuple(
                row.criterion_id
                for row in criteria
                if row.status
                is ReproductionMatchCriterionStatus.UNRESOLVED
            )
            if unresolved:
                raise ValueError(
                    "matched-result qualification has unresolved criteria: "
                    + ", ".join(unresolved)
                )
            if not any(
                row.status
                is ReproductionMatchCriterionStatus.SATISFIED
                for row in criteria
            ):
                raise ValueError(
                    "matched-result qualification requires a satisfied criterion"
                )
        object.__setattr__(self, "claim_ids", claim_ids)
        object.__setattr__(self, "criteria", criteria)
        object.__setattr__(
            self,
            "qualification_digest",
            canonical_digest(
                {
                    "qualification_id": self.qualification_id,
                    "decision": self.decision.value,
                    "run_id": self.run_id,
                    "run_manifest_digest": self.run_manifest_digest,
                    "evidence_bundle_digest": self.evidence_bundle_digest,
                    "claim_ids": claim_ids,
                    "criteria": tuple(
                        row.criterion_digest for row in criteria
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionEvidenceRef:
    """Immutable link from one reproduction to a finalized run EvidenceBundle."""

    evidence_id: str
    kind: ReproductionEvidenceKind
    run_id: str
    run_manifest_digest: str
    bundle_id: str
    evidence_bundle_digest: str
    manifest_ref: str
    manifest_sha256: str
    claim_ids: tuple[str, ...] = ()
    qualification: ReproductionEvidenceQualification | None = None
    evidence_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.evidence_id, "reproduction evidence_id")
        if not isinstance(self.kind, ReproductionEvidenceKind):
            raise TypeError(
                "reproduction evidence kind must be ReproductionEvidenceKind"
            )
        _text(self.run_id, "reproduction evidence run_id")
        _sha256(
            self.run_manifest_digest,
            "reproduction evidence run_manifest_digest",
        )
        bundle_id = _text(self.bundle_id, "reproduction evidence bundle_id")
        _sha256(
            self.evidence_bundle_digest,
            "reproduction evidence bundle digest",
        )
        manifest_ref = _text(
            self.manifest_ref,
            "reproduction evidence manifest_ref",
        )
        if manifest_ref != f"evidence/{bundle_id}/manifest.json":
            raise ValueError(
                "reproduction evidence manifest_ref must match bundle identity"
            )
        _sha256(
            self.manifest_sha256,
            "reproduction evidence manifest_sha256",
        )
        claim_ids = tuple(
            sorted(
                _strings(
                    self.claim_ids,
                    "reproduction evidence claim_ids",
                    non_empty=(
                        self.kind is ReproductionEvidenceKind.MATCHED_RESULT
                    ),
                )
            )
        )
        for claim_id in claim_ids:
            _token(claim_id, "reproduction evidence claim_id")
        object.__setattr__(self, "claim_ids", claim_ids)
        qualification = self.qualification
        if qualification is not None:
            if type(qualification) is not ReproductionEvidenceQualification:
                raise TypeError(
                    "reproduction evidence qualification must be typed"
                )
            if qualification.decision is not self.kind:
                raise ValueError(
                    "reproduction evidence qualification decision drifted"
                )
            if qualification.run_id != self.run_id:
                raise ValueError(
                    "reproduction evidence qualification run identity drifted"
                )
            if qualification.run_manifest_digest != self.run_manifest_digest:
                raise ValueError(
                    "reproduction evidence qualification manifest drifted"
                )
            if (
                qualification.evidence_bundle_digest
                != self.evidence_bundle_digest
            ):
                raise ValueError(
                    "reproduction evidence qualification bundle drifted"
                )
            if qualification.claim_ids != claim_ids:
                raise ValueError(
                    "reproduction evidence qualification claim set drifted"
                )
        if (
            self.kind is ReproductionEvidenceKind.MATCHED_RESULT
            and qualification is None
        ):
            raise ValueError(
                "matched-result evidence requires typed qualification"
            )
        object.__setattr__(
            self,
            "evidence_digest",
            canonical_digest(
                {
                    "evidence_id": self.evidence_id,
                    "kind": self.kind.value,
                    "run_id": self.run_id,
                    "run_manifest_digest": self.run_manifest_digest,
                    "bundle_id": bundle_id,
                    "evidence_bundle_digest": self.evidence_bundle_digest,
                    "manifest_ref": manifest_ref,
                    "manifest_sha256": self.manifest_sha256,
                    "claim_ids": claim_ids,
                    "qualification": (
                        None
                        if qualification is None
                        else qualification.qualification_digest
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionDefinition:
    package: str
    lifecycle: ReproductionLifecycle
    identity: ReproductionIdentity
    catalog: ReproductionCatalog
    assets: tuple[ReproductionAssetRef, ...]
    primary_executable: str | None = None
    method_program_factory: ReproductionMethodProgramFactoryBinding | None = None
    reported_results: tuple[ReportedResult, ...] = ()
    reference_baselines: tuple[ReferenceBaseline, ...] = ()
    deltas: tuple[ReproductionDelta, ...] = ()
    blockers: tuple[str, ...] = ()
    evidence_refs: tuple[ReproductionEvidenceRef, ...] = ()
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
        method_program_factory = self.method_program_factory
        if method_program_factory is not None:
            if type(method_program_factory) is not ReproductionMethodProgramFactoryBinding:
                raise TypeError(
                    "reproduction method_program_factory must be typed"
                )
            if len(executable_assets) != 1 or executable_assets[0].kind is not (
                ReproductionAssetKind.METHOD_PROGRAM
            ):
                raise ValueError(
                    "reproduction MethodProgram factory binding requires exactly "
                    "one MethodProgram executable asset"
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
        evidence_refs = self.evidence_refs
        if type(evidence_refs) is not tuple or any(
            type(row) is not ReproductionEvidenceRef for row in evidence_refs
        ):
            raise TypeError(
                "reproduction evidence_refs must contain ReproductionEvidenceRef"
            )
        evidence_refs = tuple(
            sorted(evidence_refs, key=lambda row: row.evidence_id)
        )
        evidence_ids = tuple(row.evidence_id for row in evidence_refs)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("reproduction evidence identities must be unique")

        reported_claim_ids = {
            row.claim_id for row in self.reported_results
        }
        evidence_claim_ids = {
            claim_id
            for evidence in evidence_refs
            for claim_id in evidence.claim_ids
        }
        unknown_claim_ids = evidence_claim_ids - reported_claim_ids
        if unknown_claim_ids:
            raise ValueError(
                "reproduction evidence references unknown claims: "
                + ", ".join(sorted(unknown_claim_ids))
            )

        matched_evidence = tuple(
            row
            for row in evidence_refs
            if row.kind is ReproductionEvidenceKind.MATCHED_RESULT
        )
        matched_claim_ids = {
            claim_id
            for evidence in matched_evidence
            for claim_id in evidence.claim_ids
        }
        if self.lifecycle is ReproductionLifecycle.MATCHED_REPRODUCTION:
            if not self.reported_results:
                raise ValueError(
                    "matched reproduction requires reported results"
                )
            if blockers:
                raise ValueError(
                    "matched reproduction cannot retain blockers"
                )
            if any(
                row.kind is ReproductionDeltaKind.UNRESOLVED
                for row in self.deltas
            ):
                raise ValueError(
                    "matched reproduction cannot retain unresolved deltas"
                )
            if not matched_evidence:
                raise ValueError(
                    "matched reproduction requires matched-result evidence"
                )
            if matched_claim_ids != reported_claim_ids:
                raise ValueError(
                    "matched-result evidence must cover every reported claim"
                )

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
                    "method_program_factory": (
                        None
                        if method_program_factory is None
                        else method_program_factory.binding_digest
                    ),
                    "reported_results": tuple(row.claim_digest for row in self.reported_results),
                    "reference_baselines": tuple(
                        row.baseline_digest for row in self.reference_baselines
                    ),
                    "deltas": tuple(row.delta_digest for row in self.deltas),
                    "blockers": blockers,
                    "evidence_refs": tuple(
                        row.evidence_digest for row in evidence_refs
                    ),
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
    "ReproductionEvidenceKind",
    "ReproductionEvidenceQualification",
    "ReproductionEvidenceRef",
    "ReproductionMatchCriterion",
    "ReproductionMatchCriterionStatus",
    "ReproductionMethodProgramFactoryBinding",
    "REPRODUCTION_MATCH_REQUIRED_CRITERIA",
    "ReproductionIdentity",
    "ReproductionLifecycle",
]
