"""Canonical aggregation of proof-backed Research execution bindings.

Research owns only the closure. Project manifests and Capability, Participant,
and Model systems remain the authorities for their own requirements and
provider truth. This module freezes their typed proofs into exactly one
ResearchBindingContribution and validates it through the canonical compiler.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    require_sha256,
)
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
    compile_research_plan,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    ResearchStudyDefinition,
)


def _authority_digest(value: object, field_name: str) -> str:
    digest = getattr(value, "identity_digest", None)
    if type(digest) is not str:
        raise TypeError(f"{field_name} must expose identity_digest")
    return require_sha256(digest, f"{field_name} identity_digest")


@runtime_checkable
class ResearchProjectManifestResolverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, definition: ResearchStudyDefinition) -> ProjectManifest: ...


@runtime_checkable
class ResearchCapabilityBindingResolverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(
        self,
        requirement: ProjectCapabilityRequirement,
        *,
        definition: ResearchStudyDefinition,
        resolution: ResearchRequirementResolution,
    ) -> tuple[ResearchCapabilityBinding, ...]: ...


@runtime_checkable
class ResearchParticipantBindingResolverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(
        self,
        requirement: ResearchParticipantRequirement,
        *,
        definition: ResearchStudyDefinition,
        resolution: ResearchRequirementResolution,
    ) -> ResearchParticipantBinding: ...


@runtime_checkable
class ResearchModelRoleBindingResolverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(
        self,
        requirement: ResearchModelRoleRequirement,
        *,
        definition: ResearchStudyDefinition,
        resolution: ResearchRequirementResolution,
    ) -> tuple[ResearchModelRoleBinding, ...]: ...


class CanonicalResearchBindingAuthority:
    """Join producer-owned binding proofs into one immutable Research closure."""

    def __init__(
        self,
        manifests: ResearchProjectManifestResolverPort,
        capabilities: ResearchCapabilityBindingResolverPort,
        participants: ResearchParticipantBindingResolverPort,
        models: ResearchModelRoleBindingResolverPort,
    ) -> None:
        for field_name, value, port in (
            (
                "manifests",
                manifests,
                ResearchProjectManifestResolverPort,
            ),
            (
                "capabilities",
                capabilities,
                ResearchCapabilityBindingResolverPort,
            ),
            (
                "participants",
                participants,
                ResearchParticipantBindingResolverPort,
            ),
            (
                "models",
                models,
                ResearchModelRoleBindingResolverPort,
            ),
        ):
            if not isinstance(value, port):
                raise TypeError(
                    f"Research binding authority {field_name} must satisfy typed port"
                )

        self._manifests = manifests
        self._capabilities = capabilities
        self._participants = participants
        self._models = models
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.research-binding-authority.v1",
                "manifest_authority": _authority_digest(
                    manifests,
                    "manifest authority",
                ),
                "capability_authority": _authority_digest(
                    capabilities,
                    "capability authority",
                ),
                "participant_authority": _authority_digest(
                    participants,
                    "participant authority",
                ),
                "model_authority": _authority_digest(
                    models,
                    "model authority",
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def _capability_bindings(
        self,
        definition: ResearchStudyDefinition,
        resolution: ResearchRequirementResolution,
    ) -> tuple[ResearchCapabilityBinding, ...]:
        rows: list[ResearchCapabilityBinding] = []
        for requirement in resolution.capability_requirements:
            resolved = self._capabilities.resolve(
                requirement,
                definition=definition,
                resolution=resolution,
            )
            if type(resolved) is not tuple or any(
                type(row) is not ResearchCapabilityBinding
                for row in resolved
            ):
                raise TypeError(
                    "capability binding resolver must return typed immutable tuple"
                )
            if any(
                row.requirement_id != requirement.requirement_id
                for row in resolved
            ):
                raise ValueError(
                    "capability binding resolver changed requirement identity"
                )
            if (
                requirement.cardinality
                is ProjectRequirementCardinality.EXACTLY_ONE
                and len(resolved) != 1
            ):
                raise ValueError(
                    f"capability {requirement.requirement_id!r} requires "
                    "exactly one proof-backed binding"
                )
            if (
                requirement.cardinality
                is ProjectRequirementCardinality.ONE_OR_MORE
                and not resolved
            ):
                raise ValueError(
                    f"capability {requirement.requirement_id!r} requires "
                    "at least one proof-backed binding"
                )
            ordered = tuple(
                sorted(resolved, key=lambda row: row.binding_digest)
            )
            if len({row.binding_digest for row in ordered}) != len(ordered):
                raise ValueError(
                    "capability binding resolver returned duplicate binding proof"
                )
            rows.extend(ordered)
        return tuple(rows)

    def _participant_bindings(
        self,
        definition: ResearchStudyDefinition,
        resolution: ResearchRequirementResolution,
    ) -> tuple[ResearchParticipantBinding, ...]:
        rows: list[ResearchParticipantBinding] = []
        for requirement in definition.binding_requirements.participants:
            binding = self._participants.resolve(
                requirement,
                definition=definition,
                resolution=resolution,
            )
            if type(binding) is not ResearchParticipantBinding:
                raise TypeError(
                    "participant binding resolver must return "
                    "ResearchParticipantBinding"
                )
            if binding.role != requirement.role:
                raise ValueError(
                    "participant binding resolver changed participant role"
                )
            rows.append(binding)
        return tuple(rows)

    def _model_bindings(
        self,
        definition: ResearchStudyDefinition,
        resolution: ResearchRequirementResolution,
    ) -> tuple[ResearchModelRoleBinding, ...]:
        rows: list[ResearchModelRoleBinding] = []
        for requirement in definition.binding_requirements.model_roles:
            resolved = self._models.resolve(
                requirement,
                definition=definition,
                resolution=resolution,
            )
            if type(resolved) is not tuple or any(
                type(row) is not ResearchModelRoleBinding
                for row in resolved
            ):
                raise TypeError(
                    "model binding resolver must return typed immutable tuple"
                )
            if any(
                row.role != requirement.role
                or row.requirement_id != requirement.requirement_id
                for row in resolved
            ):
                raise ValueError(
                    "model binding resolver changed model role requirement identity"
                )
            if requirement.required and not resolved:
                raise ValueError(
                    f"required model role {requirement.role!r} is unbound"
                )
            if (
                requirement.max_bindings is not None
                and len(resolved) > requirement.max_bindings
            ):
                raise ValueError(
                    f"model role {requirement.role!r} exceeds "
                    f"max_bindings={requirement.max_bindings}"
                )
            ordered = tuple(
                sorted(
                    resolved,
                    key=lambda row: (
                        row.member_index,
                        row.binding_digest,
                    ),
                )
            )
            member_indices = tuple(row.member_index for row in ordered)
            if member_indices != tuple(range(len(ordered))):
                raise ValueError(
                    "model binding panel member_index must be contiguous from zero"
                )
            rows.extend(ordered)
        return tuple(rows)

    def resolve(
        self,
        definition: ResearchStudyDefinition,
    ) -> tuple[ResearchRequirementResolution, ResearchBindingContribution]:
        """Resolve and compiler-validate one complete Study binding closure."""

        if type(definition) is not ResearchStudyDefinition:
            raise TypeError(
                "Research binding authority requires ResearchStudyDefinition"
            )
        manifest = self._manifests.resolve(definition)
        if type(manifest) is not ProjectManifest:
            raise TypeError(
                "manifest authority must return exact ProjectManifest"
            )

        resolution = resolve_research_requirements(definition, manifest)
        contribution = ResearchBindingContribution(
            requirement_resolution_digest=resolution.resolution_digest,
            capability_bindings=self._capability_bindings(
                definition,
                resolution,
            ),
            participant_bindings=self._participant_bindings(
                definition,
                resolution,
            ),
            model_role_bindings=self._model_bindings(
                definition,
                resolution,
            ),
        )

        # The compiler is the final semantic gate. The aggregation layer does
        # not reproduce its cross-domain validation rules.
        compile_research_plan(definition, resolution, contribution)
        return resolution, contribution


__all__ = [
    "CanonicalResearchBindingAuthority",
    "ResearchCapabilityBindingResolverPort",
    "ResearchModelRoleBindingResolverPort",
    "ResearchParticipantBindingResolverPort",
    "ResearchProjectManifestResolverPort",
]
