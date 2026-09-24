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
    ResearchBindingContribution,
    ResearchCapabilityBinding,
    ResearchModelRoleBinding,
    ResearchModelRoleRequirement,
    ResearchParticipantBinding,
    ResearchParticipantRequirement,
    ResearchRequirementResolution,
    ResearchStudyDefinition,
    compile_research_plan,
    resolve_research_requirements,
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
            raise LookupError(
                "no exact ProjectManifest for "
                f"project={definition.project_id!r} study={definition.study_id!r}"
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
    ) -> tuple[ResearchModelRoleBinding, ...]:
        rows: list[ResearchModelRoleBinding] = []
        for requirement in context.definition.binding_requirements.model_roles:
            resolutions = self._models.resolve(requirement, context)
            if type(resolutions) is not tuple:
                raise TypeError(
                    "model resolver must return tuple[BindingResolution, ...]"
                )
            if requirement.required and not resolutions:
                raise ValueError(
                    f"required model role {requirement.role!r} resolved empty"
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
            for member_index, resolution in enumerate(resolutions):
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
            if len(proof_digests) != len(set(proof_digests)):
                raise ValueError(
                    f"model role {requirement.role!r} resolved duplicate proofs"
                )
        return tuple(rows)

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
        contribution = ResearchBindingContribution(
            resolution.resolution_digest,
            self._capability_bindings(context),
            self._participant_bindings(context),
            self._model_bindings(context),
        )

        # The canonical compiler is the final authority for cross-domain binding
        # invariants. This is validation only; no execution or provider effects.
        compile_research_plan(definition, resolution, contribution)
        return resolution, contribution


__all__ = [
    "ResearchBindingAuthority",
    "ResearchBindingAuthorityPort",
    "ResearchBindingAuthorityError",
    "ResearchBindingResolutionContext",
    "ResearchCapabilityBindingResolverPort",
    "ResearchModelRoleBindingResolverPort",
    "ResearchParticipantBindingResolverPort",
    "ResearchProjectManifestRegistry",
    "ResearchProjectManifestResolverPort",
]
