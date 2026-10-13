"""Canonical composition authority for proof-backed research bindings.

Scientific Study declarations and ProjectManifest facts are authoritative.
Capability, Participant, and Model owners resolve their own concrete bindings.
This module only joins those frozen facts into ResearchBindingContribution and
validates the result through the canonical research compiler.
"""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from noetrium_platform.capabilities.participant.api import ProjectParticipantBinding
from noetrium_platform.foundation.governance.architecture.api import (
    BindingDiagnostic,
    BindingProof,
    BindingResolution,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    ProjectRequirementCardinality,
    project_capability_requirement_cardinality,
    project_capability_requirement_id,
    project_manifest_digest,
    project_manifest_project_id,
    project_manifest_study_ids,
    project_manifest_version,
    require_project_capability_requirement,
    require_project_manifest,
)
from noetrium_platform.research.experimentation.api import (
    ResearchBindingAssuranceGap,
    ResearchBindingContribution,
    ResearchCapabilityBinding,
    ResearchModelRoleBinding,
    ResearchParticipantBinding,
    ResearchRequirementResolution,
    binding_requirements_model_roles,
    binding_requirements_participants,
    binding_requirements_trial_provider,
    model_role_requirement_id,
    model_role_requirement_max_bindings,
    model_role_requirement_required,
    model_role_requirement_role,
    participant_requirement_role,
    require_model_role_requirement,
    require_participant_requirement,
    research_manifest_requirement_keys,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.api.research_compiler import (
    validate_research_binding_contribution,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_study_unit,
    study_binding_requirement_digest,
    study_binding_requirements,
    study_definition_digest,
    study_experiment_id,
    study_id,
    study_project_id,
)


RESEARCH_PROJECT_MANIFEST_REQUIREMENT_TRAIT = "research.project-manifest-requirement"


def research_project_manifest_requirement(
    definition: NoetriumUnit,
) -> NoetriumUnit:
    """Derive the exact manifest closure required by one Study Unit."""

    require_study_unit(definition)
    binding = study_binding_requirements(definition)
    keys = research_manifest_requirement_keys(definition)
    return structure_unit(
        "project-manifest-requirement:" + study_id(definition),
        traits=(RESEARCH_PROJECT_MANIFEST_REQUIREMENT_TRAIT,),
        parameters={
            "project_id": study_project_id(definition),
            "experiment_id": study_experiment_id(definition),
            "study_id": study_id(definition),
            "study_definition_digest": study_definition_digest(definition),
            "binding_requirement_digest": study_binding_requirement_digest(definition),
            "trial_provider_requirement_id": binding_requirements_trial_provider(binding),
            "capability_requirement_ids": keys.capability_requirement_ids,
            "method_requirement_keys": keys.method_requirement_keys,
            "configuration_ref_ids": keys.configuration_ref_ids,
            "manifest_keys_digest": keys.keys_digest,
            "participant_requirement_digests": tuple(
                row.unit_digest
                for row in binding_requirements_participants(binding)
            ),
            "model_role_requirement_digests": tuple(
                row.unit_digest
                for row in binding_requirements_model_roles(binding)
            ),
        },
    )


def require_research_project_manifest_requirement(
    value: NoetriumUnit,
) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(RESEARCH_PROJECT_MANIFEST_REQUIREMENT_TRAIT)
    ):
        raise TypeError(
            "research project manifest requirement must be NoetriumUnit"
        )
    return value


def research_project_manifest_requirement_value(
    value: NoetriumUnit,
    name: str,
):
    return require_research_project_manifest_requirement(value).parameters[name]


def research_project_manifest_capability_ids(
    value: NoetriumUnit,
) -> tuple[str, ...]:
    return tuple(
        research_project_manifest_requirement_value(
            value,
            "capability_requirement_ids",
        )
    )


def research_project_manifest_method_keys(
    value: NoetriumUnit,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        tuple(row)
        for row in research_project_manifest_requirement_value(
            value,
            "method_requirement_keys",
        )
    )


def research_project_manifest_configuration_ids(
    value: NoetriumUnit,
) -> tuple[str, ...]:
    return tuple(
        research_project_manifest_requirement_value(
            value,
            "configuration_ref_ids",
        )
    )


def research_project_manifest_requirement_digest(value: NoetriumUnit) -> str:
    return require_research_project_manifest_requirement(value).unit_digest


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

    definition: NoetriumUnit
    manifest: NoetriumUnit
    resolution: ResearchRequirementResolution
    context_digest: str

    @classmethod
    def create(
        cls,
        definition: NoetriumUnit,
        manifest: NoetriumUnit,
        resolution: ResearchRequirementResolution,
    ) -> "ResearchBindingResolutionContext":
        require_study_unit(definition)
        require_project_manifest(manifest)
        if type(resolution) is not ResearchRequirementResolution:
            raise TypeError(
                "research binding context requires ResearchRequirementResolution"
            )
        if project_manifest_digest(manifest) != resolution.project_manifest_digest:
            raise ValueError("research binding context manifest identity drifted")
        if study_binding_requirement_digest(definition) != resolution.requirements_digest:
            raise ValueError("research binding context requirement identity drifted")
        return cls(
            definition,
            manifest,
            resolution,
            canonical_digest(
                {
                    "definition_digest": study_definition_digest(definition),
                    "project_manifest_digest": project_manifest_digest(manifest),
                    "requirement_resolution_digest": resolution.resolution_digest,
                }
            ),
        )

    def __post_init__(self) -> None:
        require_study_unit(self.definition)
        require_project_manifest(self.manifest)
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

    def __init__(self, manifests: tuple[NoetriumUnit, ...]) -> None:
        if type(manifests) is not tuple or not manifests:
            raise TypeError(
                "Research ProjectManifest registry requires non-empty typed tuple"
            )
        for row in manifests:
            require_project_manifest(row)
        ordered = tuple(
            sorted(
                manifests,
                key=lambda row: (
                    project_manifest_project_id(row),
                    project_manifest_version(row),
                    project_manifest_digest(row),
                ),
            )
        )
        digests = tuple(project_manifest_digest(row) for row in ordered)
        if len(digests) != len(set(digests)):
            raise ValueError(
                "Research ProjectManifest registry contains duplicate manifests"
            )
        coverage: dict[tuple[str, str], list[NoetriumUnit]] = {}
        for manifest in ordered:
            for study_id in project_manifest_study_ids(manifest):
                coverage.setdefault(
                    (project_manifest_project_id(manifest), study_id),
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

    def resolve(self, definition: NoetriumUnit) -> NoetriumUnit:
        require_study_unit(definition)
        key = (study_project_id(definition), study_id(definition))
        manifest = self._coverage.get(key)
        if manifest is None:
            requirement = research_project_manifest_requirement(definition)
            raise ResearchBindingRequirementMissing(
                stage="project_manifest",
                requirement_id=(
                    study_project_id(definition) + ":" + study_id(definition)
                ),
                requirement_digest=research_project_manifest_requirement_digest(requirement),
            )
        if study_id(definition) not in project_manifest_study_ids(manifest):
            raise ValueError("ProjectManifest Study coverage drifted")
        if project_manifest_project_id(manifest) != study_project_id(definition):
            raise ValueError("ProjectManifest project identity drifted")
        return manifest


@runtime_checkable
class ResearchProjectManifestResolverPort(Protocol):
    """Resolve the exact ProjectManifest authority for one materialized Study."""

    def resolve(self, definition: NoetriumUnit) -> NoetriumUnit: ...


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
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[object], ...]:
        require_project_capability_requirement(requirement)
        requirement_digest = requirement.unit_digest
        key = (
            project_manifest_digest(context.manifest),
            project_capability_requirement_id(requirement),
            requirement_digest,
        )
        registration = self._by_key.get(key)
        if registration is None:
            raise ResearchBindingRequirementMissing(
                stage="capability",
                requirement_id=project_capability_requirement_id(requirement),
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
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ) -> BindingResolution[ProjectParticipantBinding]:
        require_participant_requirement(requirement)
        registration = self._by_key.get(
            (
                project_manifest_digest(context.manifest),
                requirement.unit_digest,
            )
        )
        if registration is None:
            raise ResearchBindingRequirementMissing(
                stage="participant",
                requirement_id=participant_requirement_role(requirement),
                requirement_digest=requirement.unit_digest,
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
    resolutions: tuple[BindingResolution[NoetriumUnit], ...]
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
                            else row.binding.semantic_digest
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
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[NoetriumUnit], ...]:
        require_model_role_requirement(requirement)
        registration = self._by_key.get(
            (
                project_manifest_digest(context.manifest),
                requirement.unit_digest,
            )
        )
        if registration is None:
            if model_role_requirement_required(requirement):
                raise ResearchBindingRequirementMissing(
                    stage="model",
                    requirement_id=model_role_requirement_role(requirement),
                    requirement_digest=requirement.unit_digest,
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
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[object], ...]: ...


@runtime_checkable
class ResearchParticipantBindingResolverPort(Protocol):
    """Participant owner resolver for one author participant requirement."""

    def resolve(
        self,
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ) -> BindingResolution[ProjectParticipantBinding]: ...


@runtime_checkable
class ResearchModelRoleBindingResolverPort(Protocol):
    """Model owner resolver for one named role and optional bounded panel."""

    def resolve(
        self,
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[NoetriumUnit], ...]: ...


@runtime_checkable
class ResearchBindingAuthorityPort(Protocol):
    """Single platform seam that closes one Study into exact Research bindings."""

    def resolve(
        self,
        definition: NoetriumUnit,
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
        self._cache: dict[
            str,
            tuple[ResearchRequirementResolution, ResearchBindingContribution],
        ] = {}
        self._cache_lock = RLock()
        self._inflight: dict[
            str,
            Future[tuple[ResearchRequirementResolution, ResearchBindingContribution]],
        ] = {}

    def _capability_bindings(
        self,
        context: ResearchBindingResolutionContext,
    ) -> tuple[ResearchCapabilityBinding, ...]:
        rows: list[ResearchCapabilityBinding] = []
        model_requirement_ids = {
            model_role_requirement_id(row)
            for row in binding_requirements_model_roles(study_binding_requirements(context.definition))
        }
        for requirement in context.resolution.capability_requirements:
            resolutions = self._capabilities.resolve(requirement, context)
            if type(resolutions) is not tuple:
                raise TypeError(
                    "capability resolver must return tuple[BindingResolution, ...]"
                )
            expected_count = (
                1
                if project_capability_requirement_cardinality(requirement)
                is ProjectRequirementCardinality.EXACTLY_ONE
                else None
            )
            if expected_count is not None and len(resolutions) != expected_count:
                raise ValueError(
                    f"capability {project_capability_requirement_id(requirement)!r} requires exactly "
                    f"one producer; resolved={len(resolutions)}"
                )
            if expected_count is None and not resolutions:
                raise ValueError(
                    f"capability {project_capability_requirement_id(requirement)!r} requires "
                    "one-or-more producers"
                )
            bound_rows: list[tuple[BindingProof, object]] = []
            for resolution in resolutions:
                if (
                    resolution.binding is None
                    and project_capability_requirement_id(requirement) in model_requirement_ids
                ):
                    continue
                binding, proof = _bound(
                    resolution,
                    stage="capability",
                    requirement_id=project_capability_requirement_id(requirement),
                )
                bound_rows.append((proof, binding))
            ordered = tuple(
                sorted(bound_rows, key=lambda row: row[0].digest)
            )
            proof_digests = tuple(proof.digest for proof, _binding in ordered)
            if len(proof_digests) != len(set(proof_digests)):
                raise ValueError(
                    f"capability {project_capability_requirement_id(requirement)!r} resolved "
                    "duplicate producer proofs"
                )
            rows.extend(
                ResearchCapabilityBinding(
                    project_capability_requirement_id(requirement),
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
        for requirement in binding_requirements_participants(study_binding_requirements(context.definition)):
            binding, proof = _bound(
                self._participants.resolve(requirement, context),
                stage="participant",
                requirement_id=participant_requirement_role(requirement),
            )
            if type(binding) is not ProjectParticipantBinding:
                raise TypeError(
                    "participant resolver bound payload must be "
                    "ProjectParticipantBinding"
                )
            rows.append(
                ResearchParticipantBinding(
                    participant_requirement_role(requirement),
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
        for requirement in binding_requirements_model_roles(study_binding_requirements(context.definition)):
            resolutions = self._models.resolve(requirement, context)
            if type(resolutions) is not tuple:
                raise TypeError(
                    "model resolver must return tuple[BindingResolution, ...]"
                )
            if (
                model_role_requirement_max_bindings(requirement) is not None
                and len(resolutions) > model_role_requirement_max_bindings(requirement)
            ):
                raise ValueError(
                    f"model role {model_role_requirement_role(requirement)!r} exceeds "
                    f"max_bindings={model_role_requirement_max_bindings(requirement)}"
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
                    requirement_id=model_role_requirement_role(requirement),
                )
                if type(binding) is not NoetriumUnit:
                    raise TypeError(
                        "model resolver bound payload must be NoetriumUnit"
                    )
                params = binding.parameters
                if params.get("requirement_id") != model_role_requirement_id(requirement):
                    raise ValueError(
                        "model binding Unit requirement identity drifted"
                    )
                if params.get("requirement_digest") != requirement.unit_digest:
                    raise ValueError(
                        "model binding Unit requirement digest drifted"
                    )
                if params.get("role") != model_role_requirement_role(requirement):
                    raise ValueError("model binding Unit role drifted")
                if params.get("member_index") != member_index:
                    raise ValueError(
                        "model binding Unit member ordering drifted"
                    )
                proof_digests.append(proof.digest)
                rows.append(
                    ResearchModelRoleBinding(
                        requirement_id=model_role_requirement_id(requirement),
                        requirement_digest=requirement.unit_digest,
                        binding=binding,
                        proof=proof,
                        role=model_role_requirement_role(requirement),
                        model_id=str(params["model_id"]),
                        prompt_generation_id=params.get(
                            "prompt_generation_id"
                        ),
                        prompt_digest=params.get("prompt_digest"),
                        capabilities=tuple(params["capabilities"]),
                        member_index=member_index,
                    )
                )
                member_index += 1
            if len(proof_digests) != len(set(proof_digests)):
                raise ValueError(
                    f"model role {model_role_requirement_role(requirement)!r} resolved duplicate proofs"
                )
            if model_role_requirement_required(requirement) and not proof_digests:
                gaps.append(
                    ResearchBindingAssuranceGap(
                        domain="model",
                        requirement_key=model_role_requirement_role(requirement),
                        requirement_digest=requirement.unit_digest,
                        diagnostic_digests=tuple(sorted(set(diagnostic_digests))),
                    )
                )
        return tuple(rows), tuple(gaps)

    def resolve(
        self,
        definition: NoetriumUnit,
    ) -> tuple[ResearchRequirementResolution, ResearchBindingContribution]:
        """Resolve one Study into a compiler-validated immutable binding closure."""

        require_study_unit(definition)
        cache_key = study_definition_digest(definition)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
            pending = self._inflight.get(cache_key)
            owner = pending is None
            if owner:
                pending = Future()
                self._inflight[cache_key] = pending
        assert pending is not None
        if not owner:
            # A second consumer borrows the producer's exact compiler-validated
            # closure, including the same exception if resolution fails.
            # Never hold the authority lock while waiting on independent work.
            return pending.result()

        try:
            manifest = self._manifests.resolve(definition)
            require_project_manifest(manifest)
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

            # Keep full compiler validation; singleflight only eliminates
            # duplicate concurrent work for an identical immutable Study.
            validate_research_binding_contribution(
                definition,
                resolution,
                contribution,
            )
            resolved = (resolution, contribution)
            with self._cache_lock:
                existing = self._cache.setdefault(cache_key, resolved)
                if existing != resolved:
                    raise RuntimeError(
                        "research binding authority resolved one Study definition "
                        "to multiple immutable binding closures"
                    )
                self._inflight.pop(cache_key, None)
        except BaseException as exc:
            with self._cache_lock:
                if self._inflight.get(cache_key) is pending:
                    self._inflight.pop(cache_key)
            pending.set_exception(exc)
            raise
        pending.set_result(existing)
        return existing


__all__ = [
    "RESEARCH_PROJECT_MANIFEST_REQUIREMENT_TRAIT",
    "research_project_manifest_requirement",
    "research_project_manifest_capability_ids",
    "research_project_manifest_method_keys",
    "research_project_manifest_configuration_ids",
    "research_project_manifest_requirement_digest",
    "require_research_project_manifest_requirement",
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
    "ResearchProjectManifestRegistry",
    "ResearchProjectManifestResolverPort",
]
