"""Machine-readable owner requirements for repository fleet execution.

This module never selects a provider. It compiles exact, content-addressed
requirements that owner systems must materialize before the Research OS may
admit or execute the repository reproduction fleet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.composition.research_binding_authority import (
    ResearchProjectManifestRegistry,
    ResearchProjectManifestRequirement,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api import (
    resolve_research_requirements,
)

from .fleet import ReproductionFleetMaterialization
from .research_os import (
    ReproductionExecutionRequirementKind,
    executable_reproduction_definitions,
    resolve_benchmark_split_consumers,
    resolve_execution_requirements,
    resolve_study_factory_bindings,
)


def _text(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _sha(value: str, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class ReproductionFleetPrerequisiteRequirement:
    """One pre-materialization requirement owned outside the fleet compiler."""

    stage: str
    package: str
    requirement_key: str
    requirement_digest: str
    owner: str
    requirement_digest_bound: bool = True

    def __post_init__(self) -> None:
        _text(self.stage, "fleet prerequisite stage")
        _text(self.package, "fleet prerequisite package")
        _text(self.requirement_key, "fleet prerequisite key")
        _sha(self.requirement_digest, "fleet prerequisite digest")
        _text(self.owner, "fleet prerequisite owner")
        if type(self.requirement_digest_bound) is not bool:
            raise TypeError("fleet prerequisite digest-bound flag must be bool")


@dataclass(frozen=True, slots=True)
class ReproductionFleetPrerequisiteManifest:
    requirements: tuple[ReproductionFleetPrerequisiteRequirement, ...]
    manifest_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.requirements) is not tuple or any(
            type(row) is not ReproductionFleetPrerequisiteRequirement
            for row in self.requirements
        ):
            raise TypeError("fleet prerequisite manifest requires typed tuple")
        ordered = tuple(
            sorted(
                self.requirements,
                key=lambda row: (
                    row.package,
                    row.stage,
                    row.requirement_key,
                    row.requirement_digest,
                ),
            )
        )
        keys = tuple(
            (row.package, row.stage, row.requirement_key)
            for row in ordered
        )
        if len(keys) != len(set(keys)):
            raise ValueError("fleet prerequisite requirements must be unique")
        object.__setattr__(self, "requirements", ordered)
        object.__setattr__(
            self,
            "manifest_digest",
            canonical_digest(
                {
                    "schema": "noetrium.reproduction-fleet-prerequisites.v1",
                    "requirements": tuple(
                        {
                            "stage": row.stage,
                            "package": row.package,
                            "requirement_key": row.requirement_key,
                            "requirement_digest": row.requirement_digest,
                            "owner": row.owner,
                            "requirement_digest_bound": row.requirement_digest_bound,
                        }
                        for row in ordered
                    ),
                }
            ),
        )


def compile_repository_fleet_prerequisites() -> ReproductionFleetPrerequisiteManifest:
    """Compile all authority needed before exact Study materialization is possible."""

    rows: list[ReproductionFleetPrerequisiteRequirement] = []
    for definition in executable_reproduction_definitions():
        split_consumers = resolve_benchmark_split_consumers(definition)
        for factory in resolve_study_factory_bindings(definition):
            for benchmark_id in definition.catalog.benchmark_ids:
                key = f"{factory.qualname}:{benchmark_id}"
                benchmark_requirement = factory.benchmark_requirement(
                    benchmark_id
                )
                rows.append(
                    ReproductionFleetPrerequisiteRequirement(
                        stage="benchmark",
                        package=definition.package,
                        requirement_key=key,
                        requirement_digest=canonical_digest(
                            {
                                "schema": "noetrium.reproduction-benchmark-prerequisite.v2",
                                "definition_digest": definition.definition_digest,
                                "study_factory_binding_digest": factory.binding_digest,
                                "benchmark_id": benchmark_id,
                                "benchmark_requirement_digest": (
                                    None
                                    if benchmark_requirement is None
                                    else benchmark_requirement.requirement_digest
                                ),
                                "split_axis_consumers": split_consumers,
                            }
                        ),
                        owner="benchmark",
                    )
                )

        for requirement in resolve_execution_requirements(definition):
            if requirement.kind in {
                ReproductionExecutionRequirementKind.CAPABILITY_ID,
                ReproductionExecutionRequirementKind.CAPABILITY_CLOSURE,
            }:
                stage = "reproduction_capability"
                owner = "capability"
            elif requirement.kind is ReproductionExecutionRequirementKind.PAPER_OPTION:
                stage = "paper_option"
                owner = "reproduction"
            else:
                raise RuntimeError(
                    "unmapped reproduction execution requirement kind: "
                    f"{requirement.kind.value}"
                )
            rows.append(
                ReproductionFleetPrerequisiteRequirement(
                    stage=stage,
                    package=definition.package,
                    requirement_key=requirement.parameter,
                    requirement_digest=requirement.requirement_digest,
                    owner=owner,
                )
            )
    return ReproductionFleetPrerequisiteManifest(tuple(rows))


@dataclass(frozen=True, slots=True)
class ReproductionFleetCapabilityRequirement:
    """One ProjectManifest-derived Capability authority requirement."""

    package: str
    program_id: str
    study_id: str
    project_manifest_digest: str
    requirement_key: str
    requirement_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "package",
            "program_id",
            "study_id",
            "requirement_key",
        ):
            _text(
                getattr(self, field_name),
                f"fleet capability requirement {field_name}",
            )
        _sha(
            self.project_manifest_digest,
            "fleet capability requirement ProjectManifest digest",
        )
        _sha(
            self.requirement_digest,
            "fleet capability requirement digest",
        )


@dataclass(frozen=True, slots=True)
class ReproductionFleetCapabilityRequirementManifest:
    """Capability-owner worklist compiled only after ProjectManifest authority."""

    materialization_digest: str
    project_manifest_registry_digest: str
    requirements: tuple[ReproductionFleetCapabilityRequirement, ...]
    manifest_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(
            self.materialization_digest,
            "fleet capability manifest materialization_digest",
        )
        _sha(
            self.project_manifest_registry_digest,
            "fleet capability manifest ProjectManifest registry digest",
        )
        if type(self.requirements) is not tuple or any(
            type(row) is not ReproductionFleetCapabilityRequirement
            for row in self.requirements
        ):
            raise TypeError(
                "fleet capability requirement manifest requires typed tuple"
            )
        ordered = tuple(
            sorted(
                self.requirements,
                key=lambda row: (
                    row.project_manifest_digest,
                    row.requirement_key,
                    row.requirement_digest,
                    row.program_id,
                ),
            )
        )
        keys = tuple(
            (
                row.project_manifest_digest,
                row.requirement_key,
                row.requirement_digest,
            )
            for row in ordered
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "fleet capability requirements must be unique per manifest"
            )
        object.__setattr__(self, "requirements", ordered)
        object.__setattr__(
            self,
            "manifest_digest",
            canonical_digest(
                {
                    "schema": "noetrium.reproduction-fleet-capability-requirements.v1",
                    "materialization_digest": self.materialization_digest,
                    "project_manifest_registry_digest": (
                        self.project_manifest_registry_digest
                    ),
                    "requirements": tuple(
                        {
                            "package": row.package,
                            "program_id": row.program_id,
                            "study_id": row.study_id,
                            "project_manifest_digest": (
                                row.project_manifest_digest
                            ),
                            "requirement_key": row.requirement_key,
                            "requirement_digest": row.requirement_digest,
                        }
                        for row in ordered
                    ),
                }
            ),
        )


def compile_materialized_fleet_capability_requirements(
    fleet: ReproductionFleetMaterialization,
    manifests: ResearchProjectManifestRegistry,
) -> ReproductionFleetCapabilityRequirementManifest:
    """Compile Capability-owner requirements from exact ProjectManifest truth."""

    if type(fleet) is not ReproductionFleetMaterialization:
        raise TypeError(
            "fleet capability requirement compilation requires materialized fleet"
        )
    if type(manifests) is not ResearchProjectManifestRegistry:
        raise TypeError(
            "fleet capability requirement compilation requires "
            "ResearchProjectManifestRegistry"
        )

    rows: list[ReproductionFleetCapabilityRequirement] = []
    for lane in fleet.lanes:
        study = lane.study
        manifest = manifests.resolve(study)
        resolution = resolve_research_requirements(study, manifest)
        for requirement in resolution.capability_requirements:
            rows.append(
                ReproductionFleetCapabilityRequirement(
                    package=lane.definition.package,
                    program_id=lane.program.program_id,
                    study_id=study.study_id,
                    project_manifest_digest=manifest.semantic_digest,
                    requirement_key=requirement.requirement_id,
                    requirement_digest=canonical_digest(requirement),
                )
            )

    return ReproductionFleetCapabilityRequirementManifest(
        fleet.materialization_digest,
        manifests.identity_digest,
        tuple(rows),
    )


@dataclass(frozen=True, slots=True)
class ReproductionFleetOwnerRequirement:
    """One post-materialization requirement delegated to its owning system."""

    stage: str
    owner: str
    package: str
    program_id: str
    study_id: str
    requirement_key: str
    requirement_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "stage",
            "owner",
            "package",
            "program_id",
            "study_id",
            "requirement_key",
        ):
            _text(getattr(self, field_name), f"fleet owner requirement {field_name}")
        _sha(self.requirement_digest, "fleet owner requirement digest")


@dataclass(frozen=True, slots=True)
class ReproductionFleetOwnerRequirementManifest:
    materialization_digest: str
    requirements: tuple[ReproductionFleetOwnerRequirement, ...]
    manifest_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(
            self.materialization_digest,
            "fleet owner requirement materialization_digest",
        )
        if type(self.requirements) is not tuple or any(
            type(row) is not ReproductionFleetOwnerRequirement
            for row in self.requirements
        ):
            raise TypeError("fleet owner requirement manifest requires typed tuple")
        ordered = tuple(
            sorted(
                self.requirements,
                key=lambda row: (
                    row.package,
                    row.program_id,
                    row.study_id,
                    row.stage,
                    row.requirement_key,
                    row.requirement_digest,
                ),
            )
        )
        keys = tuple(
            (
                row.program_id,
                row.stage,
                row.requirement_key,
                row.requirement_digest,
            )
            for row in ordered
        )
        if len(keys) != len(set(keys)):
            raise ValueError("fleet owner requirements must be unique")
        object.__setattr__(self, "requirements", ordered)
        object.__setattr__(
            self,
            "manifest_digest",
            canonical_digest(
                {
                    "schema": "noetrium.reproduction-fleet-owner-requirements.v1",
                    "materialization_digest": self.materialization_digest,
                    "requirements": tuple(
                        {
                            "stage": row.stage,
                            "owner": row.owner,
                            "package": row.package,
                            "program_id": row.program_id,
                            "study_id": row.study_id,
                            "requirement_key": row.requirement_key,
                            "requirement_digest": row.requirement_digest,
                        }
                        for row in ordered
                    ),
                }
            ),
        )

    def for_owner(self, owner: str) -> tuple[ReproductionFleetOwnerRequirement, ...]:
        _text(owner, "fleet owner requirement lookup")
        return tuple(row for row in self.requirements if row.owner == owner)


def compile_materialized_fleet_owner_requirements(
    fleet: ReproductionFleetMaterialization,
) -> ReproductionFleetOwnerRequirementManifest:
    """Compile exact owner requirements after benchmark/reproduction closure."""

    if type(fleet) is not ReproductionFleetMaterialization:
        raise TypeError(
            "fleet owner requirement compilation requires materialized fleet"
        )
    rows: list[ReproductionFleetOwnerRequirement] = []

    for lane in fleet.lanes:
        study = lane.study
        binding = study.binding_requirements
        common = {
            "package": lane.definition.package,
            "program_id": lane.program.program_id,
            "study_id": study.study_id,
        }

        manifest = ResearchProjectManifestRequirement.from_study(study)
        rows.append(
            ReproductionFleetOwnerRequirement(
                stage="project_manifest",
                owner="portfolio",
                requirement_key=f"{study.project_id}:{study.study_id}",
                requirement_digest=manifest.requirement_digest,
                **common,
            )
        )

        for requirement in binding.participants:
            rows.append(
                ReproductionFleetOwnerRequirement(
                    stage="participant",
                    owner="participant",
                    requirement_key=requirement.role,
                    requirement_digest=requirement.requirement_digest,
                    **common,
                )
            )

        for requirement in binding.model_roles:
            rows.append(
                ReproductionFleetOwnerRequirement(
                    stage="model",
                    owner="model",
                    requirement_key=requirement.role,
                    requirement_digest=requirement.requirement_digest,
                    **common,
                )
            )

        protocol_digest = study.trial_protocol_identity.digest()
        trial_key = binding.trial_provider_requirement_id
        rows.append(
            ReproductionFleetOwnerRequirement(
                stage="trial_provider",
                owner="experimentation",
                requirement_key=trial_key,
                requirement_digest=canonical_digest(
                    {
                        "schema": "noetrium.experiment-trial-provider-requirement.v1",
                        "study_definition_digest": study.definition_digest,
                        "trial_provider_requirement_id": trial_key,
                        "trial_protocol_digest": protocol_digest,
                    }
                ),
                **common,
            )
        )

        aggregation_key = study.aggregation_requirement_id
        rows.append(
            ReproductionFleetOwnerRequirement(
                stage="aggregation",
                owner="experimentation",
                requirement_key=aggregation_key,
                requirement_digest=canonical_digest(
                    {
                        "schema": "noetrium.experiment-aggregation-requirement.v1",
                        "study_definition_digest": study.definition_digest,
                        "aggregation_requirement_id": aggregation_key,
                    }
                ),
                **common,
            )
        )

        rows.append(
            ReproductionFleetOwnerRequirement(
                stage="reconciliation",
                owner="experimentation",
                requirement_key=trial_key,
                requirement_digest=canonical_digest(
                    {
                        "schema": "noetrium.experiment-reconciliation-requirement.v1",
                        "study_definition_digest": study.definition_digest,
                        "trial_provider_requirement_id": trial_key,
                        "trial_protocol_digest": protocol_digest,
                        "provider_identity_resolution": "research-binding-authority",
                    }
                ),
                **common,
            )
        )

    return ReproductionFleetOwnerRequirementManifest(
        fleet.materialization_digest,
        tuple(rows),
    )


__all__ = [
    "ReproductionFleetCapabilityRequirement",
    "ReproductionFleetCapabilityRequirementManifest",
    "ReproductionFleetOwnerRequirement",
    "ReproductionFleetOwnerRequirementManifest",
    "ReproductionFleetPrerequisiteManifest",
    "ReproductionFleetPrerequisiteRequirement",
    "compile_materialized_fleet_capability_requirements",
    "compile_materialized_fleet_owner_requirements",
    "compile_repository_fleet_prerequisites",
]
