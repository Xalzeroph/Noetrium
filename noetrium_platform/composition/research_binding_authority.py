"""Canonical composition authority for proof-backed research bindings.

Scientific Study declarations and ProjectManifest facts are authoritative.
Capability, Participant, and Model owners resolve their own concrete bindings.
This module only joins those frozen facts into ResearchBindingContribution and
validates the result through the canonical research compiler.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.model.api import ProjectModelBinding
from noetrium_platform.capabilities.participant.api import ProjectParticipantBinding
from noetrium_platform.foundation.governance.architecture.api import (
    BindingDiagnostic,
    BindingProof,
    BindingResolution,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectManifest,
    ProjectRequirementCardinality,
)
from noetrium_platform.research.experimentation.api import (
    ResearchBindingAssuranceGap,
    ResearchBindingContribution,
    ResearchCapabilityBinding,
    ResearchModelRoleBinding,
    ResearchModelRoleRequirement,
    ResearchParticipantBinding,
    ResearchParticipantRequirement,
    ResearchRequirementResolution,
    ResearchStudyDefinition,
    compile_research_plan,
    research_manifest_requirement_keys,
    resolve_research_requirements,
)


@dataclass(frozen=True, slots=True)
class ResearchProjectManifestRequirement:
    """Exact Study-owned request for ProjectManifest materialization.

    This is not a ProjectManifest and contains no provider choice. It freezes
    only the scientific/authoring facts a manifest authority must cover before
    owner systems may materialize provider/configuration truth.
    """

    project_id: str
    experiment_id: str
    study_id: str
    study_definition_digest: str
    binding_requirement_digest: str
    trial_provider_requirement_id: str
    capability_requirement_ids: tuple[str, ...]
    method_requirement_keys: tuple[tuple[str, str], ...]
    configuration_ref_ids: tuple[str, ...]
    manifest_keys_digest: str
    participant_requirement_digests: tuple[str, ...]
    model_role_requirement_digests: tuple[str, ...]
    requirement_digest: str

    @classmethod
    def from_study(
        cls,
        definition: ResearchStudyDefinition,
    ) -> "ResearchProjectManifestRequirement":
        if type(definition) is not ResearchStudyDefinition:
            raise TypeError(
                "ProjectManifest requirement requires ResearchStudyDefinition"
            )
        binding = definition.binding_requirements
        manifest_keys = research_manifest_requirement_keys(definition)
        payload = {
            "project_id": definition.project_id,
            "experiment_id": definition.experiment_id,
            "study_id": definition.study_id,
            "study_definition_digest": definition.definition_digest,
            "binding_requirement_digest": definition.binding_requirement_digest,
            "trial_provider_requirement_id": (
                binding.trial_provider_requirement_id
            ),
            "capability_requirement_ids": (
                manifest_keys.capability_requirement_ids
            ),
            "method_requirement_keys": manifest_keys.method_requirement_keys,
            "configuration_ref_ids": manifest_keys.configuration_ref_ids,
            "manifest_keys_digest": manifest_keys.keys_digest,
            "participant_requirement_digests": tuple(
                row.requirement_digest for row in binding.participants
            ),
            "model_role_requirement_digests": tuple(
                row.requirement_digest for row in binding.model_roles
            ),
        }
        return cls(
            **payload,
            requirement_digest=canonical_digest(payload),
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("project_id", self.project_id),
            ("experiment_id", self.experiment_id),
            ("study_id", self.study_id),
            (
                "trial_provider_requirement_id",
                self.trial_provider_requirement_id,
            ),
        ):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    f"ProjectManifest requirement {field_name} "
                    "must be canonical text"
                )
        for field_name, value in (
            ("study_definition_digest", self.study_definition_digest),
            ("binding_requirement_digest", self.binding_requirement_digest),
            ("manifest_keys_digest", self.manifest_keys_digest),
            ("requirement_digest", self.requirement_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"ProjectManifest requirement {field_name} "
                    "must be lowercase SHA-256"
                )
        if type(self.capability_requirement_ids) is not tuple:
            raise TypeError(
                "ProjectManifest requirement capability_requirement_ids must be tuple"
            )
        if len(self.capability_requirement_ids) != len(
            set(self.capability_requirement_ids)
        ):
            raise ValueError(
                "ProjectManifest requirement capability_requirement_ids must be unique"
            )
        if type(self.method_requirement_keys) is not tuple:
            raise TypeError(
                "ProjectManifest requirement method_requirement_keys must be tuple"
            )
        if len(self.method_requirement_keys) != len(
            set(self.method_requirement_keys)
        ):
            raise ValueError(
                "ProjectManifest requirement method_requirement_keys must be unique"
            )
        if type(self.configuration_ref_ids) is not tuple:
            raise TypeError(
                "ProjectManifest requirement configuration_ref_ids must be tuple"
            )
        if len(self.configuration_ref_ids) != len(
            set(self.configuration_ref_ids)
        ):
            raise ValueError(
                "ProjectManifest requirement configuration_ref_ids must be unique"
            )
        selected = canonical_digest(
            {
                "capability_requirement_ids": self.capability_requirement_ids,
                "method_requirement_keys": self.method_requirement_keys,
                "configuration_ref_ids": self.configuration_ref_ids,
            }
        )
        if selected != self.manifest_keys_digest:
            raise ValueError("ProjectManifest requirement key digest drifted")

        for field_name, values in (
            (
                "participant_requirement_digests",
                self.participant_requirement_digests,
            ),
            (
                "model_role_requirement_digests",
                self.model_role_requirement_digests,
            ),
        ):
            if type(values) is not tuple:
                raise TypeError(
                    f"ProjectManifest requirement {field_name} must be tuple"
                )
            if len(values) != len(set(values)):
                raise ValueError(
                    f"ProjectManifest requirement {field_name} must be unique"
                )
            for value in values:
                if (
                    type(value) is not str
                    or len(value) != 64
                    or any(ch not in "0123456789abcdef" for ch in value)
                ):
                    raise ValueError(
                        f"ProjectManifest requirement {field_name} values "
                        "must be lowercase SHA-256"
                    )
        expected = canonical_digest(
            {
                "project_id": self.project_id,
                "experiment_id": self.experiment_id,
                "study_id": self.study_id,
                "study_definition_digest": self.study_definition_digest,
                "binding_requirement_digest": self.binding_requirement_digest,
                "trial_provider_requirement_id": (
                    self.trial_provider_requirement_id
                ),
                "capability_requirement_ids": self.capability_requirement_ids,
                "method_requirement_keys": self.method_requirement_keys,
                "configuration_ref_ids": self.configuration_ref_ids,
                "manifest_keys_digest": self.manifest_keys_digest,
                "participant_requirement_digests": (
                    self.participant_requirement_digests
                ),
                "model_role_requirement_digests": (
                    self.model_role_requirement_digests
                ),
            }
        )
        if self.requirement_digest != expected:
            raise ValueError("ProjectManifest requirement digest drifted")


class ResearchBindingRequirementMissing(LookupError):
    """An exact owner-system Research binding requirement has no registration."""

    def __init__(
        self,
        *,
        stage: str,
        requirement_id: str,
        requirement_digest: str,
    ) -> None:
        if (
            type(stage) is not str
            or not stage.strip()
            or stage != stage.strip()
        ):
            raise ValueError("missing Research binding stage must be canonical text")
        if (
            type(requirement_id) is not str
            or not requirement_id.strip()
            or requirement_id != requirement_id.strip()
        ):
            raise ValueError(
                "missing Research binding requirement_id must be canonical text"
            )
        if (
            type(requirement_digest) is not str
            or len(requirement_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in requirement_digest)
        ):
            raise ValueError(
                "missing Research binding requirement_digest must be lowercase SHA-256"
            )
        self.stage = stage
        self.requirement_id = requirement_id
        self.requirement_digest = requirement_digest
        self.error_digest = canonical_digest(
            {
                "stage": stage,
                "requirement_id": requirement_id,
                "requirement_digest": requirement_digest,
            }
        )
        super().__init__(
            f"no exact {stage} binding registration for {requirement_id!r}"
        )


@dataclass(frozen=True, slots=True)
class ResearchBindingResolutionContext:
    """Frozen input shared with owner-system binding resolvers."""

    definition: ResearchStudyDefinition
    manifest: ProjectManifest
    resolution: ResearchRequirementResolution
    context_digest: str

    @classmethod
    def create(
        cls,
        definition: ResearchStudyDefinition,
        manifest: ProjectManifest,
        resolution: ResearchRequirementResolution,
    ) -> "ResearchBindingResolutionContext":
        if type(definition) is not ResearchStudyDefinition:
            raise TypeError("research binding context requires ResearchStudyDefinition")
        if type(manifest) is not ProjectManifest:
            raise TypeError("research binding context requires ProjectManifest")
        if type(resolution) is not ResearchRequirementResolution:
            raise TypeError(
                "research binding context requires ResearchRequirementResolution"
            )
        if manifest.semantic_digest != resolution.project_manifest_digest:
            raise ValueError("research binding context manifest identity drifted")
        if definition.binding_requirement_digest != resolution.requirements_digest:
            raise ValueError("research binding context requirement identity drifted")
        return cls(
            definition,
            manifest,
            resolution,
            canonical_digest(
                {
                    "definition_digest": definition.definition_digest,
                    "project_manifest_digest": manifest.semantic_digest,
                    "requirement_resolution_digest": resolution.resolution_digest,
                }
            ),
        )

    def __post_init__(self) -> None:
        if type(self.definition) is not ResearchStudyDefinition:
            raise TypeError("research binding context definition must be typed")
        if type(self.manifest) is not ProjectManifest:
            raise TypeError("research binding context manifest must be typed")
        if type(self.resolution) is not ResearchRequirementResolution:
            raise TypeError("research binding context resolution must be typed")
        if (
            type(self.context_digest) is not str
            or len(self.context_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.context_digest)
        ):
            raise ValueError(
                "research binding context digest must be lowercase SHA-256"
            )


class ResearchProjectManifestRegistry:
    """Exact immutable ProjectManifest authority for materialized Studies."""

    def __init__(self, manifests: tuple[ProjectManifest, ...]) -> None:
        if type(manifests) is not tuple or not manifests:
            raise TypeError(
                "Research ProjectManifest registry requires non-empty typed tuple"
            )
        if any(type(row) is not ProjectManifest for row in manifests):
            raise TypeError(
                "Research ProjectManifest registry manifests must be typed"
            )
        ordered = tuple(
            sorted(
                manifests,
                key=lambda row: (
                    row.project.identity.project_id,
                    row.project.identity.version,
                    row.semantic_digest,
                ),
            )
        )
        digests = tuple(row.semantic_digest for row in ordered)
        if len(digests) != len(set(digests)):
            raise ValueError(
                "Research ProjectManifest registry contains duplicate manifests"
            )
        coverage: dict[tuple[str, str], list[ProjectManifest]] = {}
        for manifest in ordered:
            for study_id in manifest.study_ids:
                coverage.setdefault(
                    (manifest.project.identity.project_id, study_id),
                    [],
                ).append(manifest)
        ambiguous = tuple(
            sorted(
                key for key, rows in coverage.items()
                if len(rows) != 1
            )
        )
        if ambiguous:
            raise ValueError(
                "Research ProjectManifest registry has ambiguous Study coverage: "
                f"{ambiguous}"
            )
        self._manifests = ordered
        self._coverage = {
            key: rows[0] for key, rows in coverage.items()
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.research-project-manifest-registry.v1",
                "manifests": digests,
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(self, definition: ResearchStudyDefinition) -> ProjectManifest:
        if type(definition) is not ResearchStudyDefinition:
            raise TypeError(
                "Research ProjectManifest registry requires ResearchStudyDefinition"
            )
        key = (definition.project_id, definition.study_id)
        manifest = self._coverage.get(key)
        if manifest is None:
            requirement = ResearchProjectManifestRequirement.from_study(
                definition
            )
            raise ResearchBindingRequirementMissing(
                stage="project_manifest",
                requirement_id=(
                    definition.project_id + ":" + definition.study_id
                ),
                requirement_digest=requirement.requirement_digest,
            )
        if definition.study_id not in manifest.study_ids:
            raise ValueError("ProjectManifest Study coverage drifted")
        if manifest.project.identity.project_id != definition.project_id:
            raise ValueError("ProjectManifest project identity drifted")
        return manifest


@runtime_checkable
class ResearchProjectManifestResolverPort(Protocol):
    """Resolve the exact ProjectManifest authority for one materialized Study."""

    def resolve(self, definition: ResearchStudyDefinition) -> ProjectManifest: ...


@dataclass(frozen=True, slots=True)
class ResearchCapabilityBindingRegistration:
    project_manifest_digest: str
    requirement_id: str
    requirement_digest: str
    resolutions: tuple[BindingResolution[object], ...]
    registration_digest: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("project_manifest_digest", self.project_manifest_digest),
            ("requirement_digest", self.requirement_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"Research capability registration {field_name} "
                    "must be lowercase SHA-256"
                )
        if (
            type(self.requirement_id) is not str
            or not self.requirement_id.strip()
            or self.requirement_id != self.requirement_id.strip()
        ):
            raise ValueError(
                "Research capability registration requirement_id "
                "must be canonical text"
            )
        if type(self.resolutions) is not tuple or not self.resolutions:
            raise TypeError(
                "Research capability registration requires non-empty "
                "BindingResolution tuple"
            )
        if any(type(row) is not BindingResolution for row in self.resolutions):
            raise TypeError(
                "Research capability registration resolutions must be canonical "
                "BindingResolution values"
            )
        expected = canonical_digest(
            {
                "project_manifest_digest": self.project_manifest_digest,
                "requirement_id": self.requirement_id,
                "requirement_digest": self.requirement_digest,
                "resolutions": tuple(
                    row.projection_digest for row in self.resolutions
                ),
            }
        )
        if self.registration_digest:
            if self.registration_digest != expected:
                raise ValueError(
                    "Research capability registration digest drifted"
                )
        else:
            object.__setattr__(self, "registration_digest", expected)


class ResearchCapabilityBindingRegistry:
    """Exact proof-backed Capability results keyed by manifest + requirement."""

    def __init__(
        self,
        registrations: tuple[ResearchCapabilityBindingRegistration, ...],
    ) -> None:
        if type(registrations) is not tuple:
            raise TypeError(
                "Research capability registry registrations must be tuple"
            )
        if any(
            type(row) is not ResearchCapabilityBindingRegistration
            for row in registrations
        ):
            raise TypeError(
                "Research capability registry registrations must be typed"
            )
        keys = tuple(
            (
                row.project_manifest_digest,
                row.requirement_id,
                row.requirement_digest,
            )
            for row in registrations
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Research capability registry contains duplicate requirement authority"
            )
        self._registrations = tuple(
            sorted(registrations, key=lambda row: row.registration_digest)
        )
        self._by_key = {
            (
                row.project_manifest_digest,
                row.requirement_id,
                row.requirement_digest,
            ): row
            for row in self._registrations
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.research-capability-binding-registry.v1",
                "registrations": tuple(
                    row.registration_digest for row in self._registrations
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        requirement: ProjectCapabilityRequirement,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[object], ...]:
        if type(requirement) is not ProjectCapabilityRequirement:
            raise TypeError(
                "Research capability registry requires ProjectCapabilityRequirement"
            )
        requirement_digest = canonical_digest(requirement)
        key = (
            context.manifest.semantic_digest,
            requirement.requirement_id,
            requirement_digest,
        )
        registration = self._by_key.get(key)
        if registration is None:
            raise ResearchBindingRequirementMissing(
                stage="capability",
                requirement_id=requirement.requirement_id,
                requirement_digest=requirement_digest,
            )
        for resolution in registration.resolutions:
            if resolution.binding is None:
                continue
            proof = resolution.proof
            if proof is None:
                raise ValueError(
                    "bound Capability resolution lost BindingProof"
                )
            if proof.subject != context.resolution.project_subject:
                raise ValueError(
                    "Capability binding proof project subject drifted"
                )
            if proof.requirement_digest.value != requirement_digest:
                raise ValueError(
                    "Capability binding proof requirement identity drifted"
                )
        return registration.resolutions


@dataclass(frozen=True, slots=True)
class ResearchParticipantBindingRegistration:
    project_manifest_digest: str
    research_requirement_digest: str
    resolution: BindingResolution[ProjectParticipantBinding]
    registration_digest: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("project_manifest_digest", self.project_manifest_digest),
            ("research_requirement_digest", self.research_requirement_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"Research participant registration {field_name} "
                    "must be lowercase SHA-256"
                )
        if type(self.resolution) is not BindingResolution:
            raise TypeError(
                "Research participant registration requires BindingResolution"
            )
        domain_binding_digest = (
            None
            if self.resolution.binding is None
            else self.resolution.binding.digest()
        )
        expected = canonical_digest(
            {
                "project_manifest_digest": self.project_manifest_digest,
                "research_requirement_digest": self.research_requirement_digest,
                "resolution_projection_digest": self.resolution.projection_digest,
                "domain_binding_digest": domain_binding_digest,
            }
        )
        if self.registration_digest:
            if self.registration_digest != expected:
                raise ValueError(
                    "Research participant registration digest drifted"
                )
        else:
            object.__setattr__(self, "registration_digest", expected)


class ResearchParticipantBindingRegistry:
    """Exact Participant owner results keyed by manifest + Research requirement."""

    def __init__(
        self,
        registrations: tuple[ResearchParticipantBindingRegistration, ...],
    ) -> None:
        if type(registrations) is not tuple:
            raise TypeError(
                "Research participant registry registrations must be tuple"
            )
        if any(
            type(row) is not ResearchParticipantBindingRegistration
            for row in registrations
        ):
            raise TypeError(
                "Research participant registry registrations must be typed"
            )
        keys = tuple(
            (
                row.project_manifest_digest,
                row.research_requirement_digest,
            )
            for row in registrations
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Research participant registry contains duplicate requirement authority"
            )
        self._registrations = tuple(
            sorted(registrations, key=lambda row: row.registration_digest)
        )
        self._by_key = {
            (
                row.project_manifest_digest,
                row.research_requirement_digest,
            ): row
            for row in self._registrations
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.research-participant-binding-registry.v1",
                "registrations": tuple(
                    row.registration_digest for row in self._registrations
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        requirement: ResearchParticipantRequirement,
        context: ResearchBindingResolutionContext,
    ) -> BindingResolution[ProjectParticipantBinding]:
        if type(requirement) is not ResearchParticipantRequirement:
            raise TypeError(
                "Research participant registry requires "
                "ResearchParticipantRequirement"
            )
        registration = self._by_key.get(
            (
                context.manifest.semantic_digest,
                requirement.requirement_digest,
            )
        )
        if registration is None:
            raise ResearchBindingRequirementMissing(
                stage="participant",
                requirement_id=requirement.role,
                requirement_digest=requirement.requirement_digest,
            )
        resolution = registration.resolution
        if resolution.binding is not None:
            proof = resolution.proof
            if proof is None:
                raise ValueError(
                    "bound Participant resolution lost BindingProof"
                )
            if proof.subject != context.resolution.project_subject:
                raise ValueError(
                    "Participant binding proof project subject drifted"
                )
        return resolution


@dataclass(frozen=True, slots=True)
class ResearchModelRoleBindingRegistration:
    project_manifest_digest: str
    research_requirement_digest: str
    resolutions: tuple[BindingResolution[ProjectModelBinding], ...]
    registration_digest: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("project_manifest_digest", self.project_manifest_digest),
            ("research_requirement_digest", self.research_requirement_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"Research model registration {field_name} "
                    "must be lowercase SHA-256"
                )
        if type(self.resolutions) is not tuple:
            raise TypeError(
                "Research model registration resolutions must be tuple"
            )
        if any(type(row) is not BindingResolution for row in self.resolutions):
            raise TypeError(
                "Research model registration resolutions must be canonical "
                "BindingResolution values"
            )
        expected = canonical_digest(
            {
                "project_manifest_digest": self.project_manifest_digest,
                "research_requirement_digest": self.research_requirement_digest,
                "resolutions": tuple(
                    {
                        "projection_digest": row.projection_digest,
                        "domain_binding_digest": (
                            None
                            if row.binding is None
                            else row.binding.digest()
                        ),
                    }
                    for row in self.resolutions
                ),
            }
        )
        if self.registration_digest:
            if self.registration_digest != expected:
                raise ValueError("Research model registration digest drifted")
        else:
            object.__setattr__(self, "registration_digest", expected)


class ResearchModelRoleBindingRegistry:
    """Exact Model owner results keyed by manifest + Research model requirement."""

    def __init__(
        self,
        registrations: tuple[ResearchModelRoleBindingRegistration, ...],
    ) -> None:
        if type(registrations) is not tuple:
            raise TypeError("Research model registry registrations must be tuple")
        if any(
            type(row) is not ResearchModelRoleBindingRegistration
            for row in registrations
        ):
            raise TypeError(
                "Research model registry registrations must be typed"
            )
        keys = tuple(
            (
                row.project_manifest_digest,
                row.research_requirement_digest,
            )
            for row in registrations
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Research model registry contains duplicate requirement authority"
            )
        self._registrations = tuple(
            sorted(registrations, key=lambda row: row.registration_digest)
        )
        self._by_key = {
            (
                row.project_manifest_digest,
                row.research_requirement_digest,
            ): row
            for row in self._registrations
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.research-model-binding-registry.v1",
                "registrations": tuple(
                    row.registration_digest for row in self._registrations
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        requirement: ResearchModelRoleRequirement,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[ProjectModelBinding], ...]:
        if type(requirement) is not ResearchModelRoleRequirement:
            raise TypeError(
                "Research model registry requires ResearchModelRoleRequirement"
            )
        registration = self._by_key.get(
            (
                context.manifest.semantic_digest,
                requirement.requirement_digest,
            )
        )
        if registration is None:
            if requirement.required:
                raise ResearchBindingRequirementMissing(
                    stage="model",
                    requirement_id=requirement.role,
                    requirement_digest=requirement.requirement_digest,
                )
            return ()
        for resolution in registration.resolutions:
            if resolution.binding is None:
                continue
            proof = resolution.proof
            if proof is None:
                raise ValueError("bound Model resolution lost BindingProof")
            if proof.subject != context.resolution.project_subject:
                raise ValueError("Model binding proof project subject drifted")
        return registration.resolutions


@runtime_checkable
class ResearchCapabilityBindingResolverPort(Protocol):
    """Capability owner resolver; one-or-more requirements may return many proofs."""

    def resolve(
        self,
        requirement: ProjectCapabilityRequirement,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[object], ...]: ...


@runtime_checkable
class ResearchParticipantBindingResolverPort(Protocol):
    """Participant owner resolver for one author participant requirement."""

    def resolve(
        self,
        requirement: ResearchParticipantRequirement,
        context: ResearchBindingResolutionContext,
    ) -> BindingResolution[ProjectParticipantBinding]: ...


@runtime_checkable
class ResearchModelRoleBindingResolverPort(Protocol):
    """Model owner resolver for one named role and optional bounded panel."""

    def resolve(
        self,
        requirement: ResearchModelRoleRequirement,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[ProjectModelBinding], ...]: ...


@runtime_checkable
class ResearchBindingAuthorityPort(Protocol):
    """Single platform seam that closes one Study into exact Research bindings."""

    def resolve(
        self,
        definition: ResearchStudyDefinition,
    ) -> tuple[ResearchRequirementResolution, ResearchBindingContribution]: ...


class ResearchBindingAuthorityError(RuntimeError):
    """An owner resolver could not provide a proof-backed binding."""

    def __init__(
        self,
        *,
        stage: str,
        requirement_id: str,
        diagnostics: tuple[BindingDiagnostic, ...],
    ) -> None:
        if type(stage) is not str or not stage.strip():
            raise ValueError("research binding error stage is required")
        if type(requirement_id) is not str or not requirement_id.strip():
            raise ValueError("research binding error requirement_id is required")
        if type(diagnostics) is not tuple or not diagnostics or any(
            type(row) is not BindingDiagnostic for row in diagnostics
        ):
            raise TypeError(
                "research binding error diagnostics must be non-empty typed tuple"
            )
        self.stage = stage
        self.requirement_id = requirement_id
        self.diagnostics = tuple(
            sorted(diagnostics, key=lambda row: row.machine_digest)
        )
        self.error_digest = canonical_digest(
            {
                "stage": stage,
                "requirement_id": requirement_id,
                "diagnostics": tuple(
                    row.machine_digest for row in self.diagnostics
                ),
            }
        )
        super().__init__(
            f"research binding unresolved at {stage}:{requirement_id}; "
            f"diagnostics={tuple(row.code.value for row in self.diagnostics)}"
        )


def _bound(
    value: object,
    *,
    stage: str,
    requirement_id: str,
) -> tuple[object, BindingProof]:
    if type(value) is not BindingResolution:
        raise TypeError(
            f"{stage} resolver must return canonical BindingResolution"
        )
    if value.binding is None:
        raise ResearchBindingAuthorityError(
            stage=stage,
            requirement_id=requirement_id,
            diagnostics=value.diagnostics,
        )
    proof = value.proof
    if not isinstance(proof, BindingProof):
        raise TypeError(f"{stage} bound resolution lost BindingProof")
    return value.binding, proof


class ResearchBindingAuthority:
    """Compose exact Project/Capability/Participant/Model binding authorities."""

    def __init__(
        self,
        manifests: ResearchProjectManifestResolverPort,
        capabilities: ResearchCapabilityBindingResolverPort,
        participants: ResearchParticipantBindingResolverPort,
        models: ResearchModelRoleBindingResolverPort,
    ) -> None:
        if not isinstance(manifests, ResearchProjectManifestResolverPort):
            raise TypeError(
                "research binding authority requires ProjectManifest resolver"
            )
        if not isinstance(capabilities, ResearchCapabilityBindingResolverPort):
            raise TypeError(
                "research binding authority requires Capability binding resolver"
            )
        if not isinstance(participants, ResearchParticipantBindingResolverPort):
            raise TypeError(
                "research binding authority requires Participant binding resolver"
            )
        if not isinstance(models, ResearchModelRoleBindingResolverPort):
            raise TypeError(
                "research binding authority requires Model role binding resolver"
            )
        self._manifests = manifests
        self._capabilities = capabilities
        self._participants = participants
        self._models = models

    def _capability_bindings(
        self,
        context: ResearchBindingResolutionContext,
    ) -> tuple[ResearchCapabilityBinding, ...]:
        rows: list[ResearchCapabilityBinding] = []
        model_requirement_ids = {
            row.requirement_id
            for row in context.definition.binding_requirements.model_roles
        }
        for requirement in context.resolution.capability_requirements:
            resolutions = self._capabilities.resolve(requirement, context)
            if type(resolutions) is not tuple:
                raise TypeError(
                    "capability resolver must return tuple[BindingResolution, ...]"
                )
            expected_count = (
                1
                if requirement.cardinality
                is ProjectRequirementCardinality.EXACTLY_ONE
                else None
            )
            if expected_count is not None and len(resolutions) != expected_count:
                raise ValueError(
                    f"capability {requirement.requirement_id!r} requires exactly "
                    f"one producer; resolved={len(resolutions)}"
                )
            if expected_count is None and not resolutions:
                raise ValueError(
                    f"capability {requirement.requirement_id!r} requires "
                    "one-or-more producers"
                )
            bound_rows: list[tuple[BindingProof, object]] = []
            for resolution in resolutions:
                if (
                    resolution.binding is None
                    and requirement.requirement_id in model_requirement_ids
                ):
                    continue
                binding, proof = _bound(
                    resolution,
                    stage="capability",
                    requirement_id=requirement.requirement_id,
                )
                bound_rows.append((proof, binding))
            ordered = tuple(
                sorted(bound_rows, key=lambda row: row[0].digest)
            )
            proof_digests = tuple(proof.digest for proof, _binding in ordered)
            if len(proof_digests) != len(set(proof_digests)):
                raise ValueError(
                    f"capability {requirement.requirement_id!r} resolved "
                    "duplicate producer proofs"
                )
            rows.extend(
                ResearchCapabilityBinding(
                    requirement.requirement_id,
                    proof,
                )
                for proof, _binding in ordered
            )
        return tuple(rows)

    def _participant_bindings(
        self,
        context: ResearchBindingResolutionContext,
    ) -> tuple[ResearchParticipantBinding, ...]:
        rows: list[ResearchParticipantBinding] = []
        for requirement in context.definition.binding_requirements.participants:
            binding, proof = _bound(
                self._participants.resolve(requirement, context),
                stage="participant",
                requirement_id=requirement.role,
            )
            if type(binding) is not ProjectParticipantBinding:
                raise TypeError(
                    "participant resolver bound payload must be "
                    "ProjectParticipantBinding"
                )
            rows.append(
                ResearchParticipantBinding(
                    requirement.role,
                    binding,
                    proof,
                )
            )
        return tuple(rows)

    def _model_bindings(
        self,
        context: ResearchBindingResolutionContext,
    ) -> tuple[
        tuple[ResearchModelRoleBinding, ...],
        tuple[ResearchBindingAssuranceGap, ...],
    ]:
        rows: list[ResearchModelRoleBinding] = []
        gaps: list[ResearchBindingAssuranceGap] = []
        for requirement in context.definition.binding_requirements.model_roles:
            resolutions = self._models.resolve(requirement, context)
            if type(resolutions) is not tuple:
                raise TypeError(
                    "model resolver must return tuple[BindingResolution, ...]"
                )
            if (
                requirement.max_bindings is not None
                and len(resolutions) > requirement.max_bindings
            ):
                raise ValueError(
                    f"model role {requirement.role!r} exceeds "
                    f"max_bindings={requirement.max_bindings}"
                )
            proof_digests: list[str] = []
            diagnostic_digests: list[str] = []
            member_index = 0
            for resolution in resolutions:
                if resolution.binding is None:
                    diagnostic_digests.extend(
                        row.machine_digest for row in resolution.diagnostics
                    )
                    continue
                binding, proof = _bound(
                    resolution,
                    stage="model",
                    requirement_id=requirement.role,
                )
                if type(binding) is not ProjectModelBinding:
                    raise TypeError(
                        "model resolver bound payload must be ProjectModelBinding"
                    )
                proof_digests.append(proof.digest)
                rows.append(
                    ResearchModelRoleBinding(
                        requirement.requirement_id,
                        binding,
                        proof,
                        requirement.role,
                        member_index,
                    )
                )
                member_index += 1
            if len(proof_digests) != len(set(proof_digests)):
                raise ValueError(
                    f"model role {requirement.role!r} resolved duplicate proofs"
                )
            if requirement.required and not proof_digests:
                gaps.append(
                    ResearchBindingAssuranceGap(
                        domain="model",
                        requirement_key=requirement.role,
                        requirement_digest=requirement.requirement_digest,
                        diagnostic_digests=tuple(sorted(set(diagnostic_digests))),
                    )
                )
        return tuple(rows), tuple(gaps)

    def resolve(
        self,
        definition: ResearchStudyDefinition,
    ) -> tuple[ResearchRequirementResolution, ResearchBindingContribution]:
        """Resolve one Study into a compiler-validated immutable binding closure."""

        if type(definition) is not ResearchStudyDefinition:
            raise TypeError(
                "research binding authority requires ResearchStudyDefinition"
            )
        manifest = self._manifests.resolve(definition)
        if type(manifest) is not ProjectManifest:
            raise TypeError(
                "ProjectManifest resolver must return canonical ProjectManifest"
            )
        resolution = resolve_research_requirements(definition, manifest)
        context = ResearchBindingResolutionContext.create(
            definition,
            manifest,
            resolution,
        )
        model_bindings, assurance_gaps = self._model_bindings(context)
        contribution = ResearchBindingContribution(
            resolution.resolution_digest,
            self._capability_bindings(context),
            self._participant_bindings(context),
            model_bindings,
            assurance_gaps,
        )

        # The canonical compiler is the final authority for cross-domain binding
        # invariants. This is validation only; no execution or provider effects.
        compile_research_plan(definition, resolution, contribution)
        return resolution, contribution


__all__ = [
    "ResearchBindingAuthority",
    "ResearchBindingAuthorityPort",
    "ResearchBindingAuthorityError",
    "ResearchBindingRequirementMissing",
    "ResearchBindingResolutionContext",
    "ResearchCapabilityBindingResolverPort",
    "ResearchModelRoleBindingRegistry",
    "ResearchModelRoleBindingRegistration",
    "ResearchParticipantBindingRegistry",
    "ResearchParticipantBindingRegistration",
    "ResearchCapabilityBindingRegistry",
    "ResearchCapabilityBindingRegistration",
    "ResearchModelRoleBindingResolverPort",
    "ResearchParticipantBindingResolverPort",
    "ResearchProjectManifestRequirement",
    "ResearchProjectManifestRegistry",
    "ResearchProjectManifestResolverPort",
]
