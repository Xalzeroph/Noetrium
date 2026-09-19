from __future__ import annotations

from collections.abc import Callable

from noetrium_platform.capabilities.participant.api.project import (
    ParticipantBindingDiagnostic,
    ParticipantBindingDiagnosticCode,
    ParticipantBindingDiagnosticSeverity,
    ParticipantProjectBindingError,
    ParticipantProviderProfile,
    ParticipantRequirement,
    ProjectParticipantBinding,
    ProjectParticipantProviderPort,
)
from noetrium_platform.capabilities.participant.binding.api.contracts import ParticipantBindingResolverPort
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)


RuntimeSelector = Callable[[ParticipantRequirement], ParticipantSessionRuntimeIdentity]


def _diagnostic(
    profile: ParticipantProviderProfile,
    requirement: ParticipantRequirement,
    code: ParticipantBindingDiagnosticCode,
    message: str,
) -> ParticipantBindingDiagnostic:
    return ParticipantBindingDiagnostic(
        code=code,
        severity=ParticipantBindingDiagnosticSeverity.ERROR,
        message=message,
        requirement_digest=requirement.digest(),
        provider_id=profile.provider_id,
    )


class RuntimeParticipantProjectProvider(ProjectParticipantProviderPort):
    """Reference adapter from participant runtime binding to the project seam."""

    def __init__(
        self,
        profile: ParticipantProviderProfile,
        resolver: ParticipantBindingResolverPort,
        runtime_selector: RuntimeSelector,
    ) -> None:
        if not isinstance(profile, ParticipantProviderProfile):
            raise TypeError("project participant provider profile must be typed")
        self._profile = profile
        self._resolver = resolver
        self._runtime_selector = runtime_selector

    @property
    def profile(self) -> ParticipantProviderProfile:
        return self._profile

    def _preflight(
        self, requirement: ParticipantRequirement
    ) -> tuple[ParticipantBindingDiagnostic, ...]:
        if not isinstance(requirement, ParticipantRequirement):
            raise TypeError("project participant requirement must be typed")
        if requirement.implementation.kind not in self._profile.supported_kinds:
            return (
                _diagnostic(
                    self._profile,
                    requirement,
                    ParticipantBindingDiagnosticCode.KIND_UNSUPPORTED,
                    f"participant kind is not supported: {requirement.implementation.kind}",
                ),
            )
        missing = tuple(
            capability
            for capability in requirement.required_capabilities
            if capability not in self._profile.capabilities
        )
        if missing:
            return (
                _diagnostic(
                    self._profile,
                    requirement,
                    ParticipantBindingDiagnosticCode.CAPABILITY_MISSING,
                    "participant provider lacks capabilities: " + ", ".join(missing),
                ),
            )
        return ()

    def diagnose(
        self, requirement: ParticipantRequirement
    ) -> tuple[ParticipantBindingDiagnostic, ...]:
        diagnostics = self._preflight(requirement)
        if diagnostics:
            return diagnostics
        try:
            runtime = self._runtime_selector(requirement)
            binding = ParticipantRuntimeBinding(
                role=requirement.role,
                implementation=requirement.implementation,
                runtime=runtime,
                configuration_digest=requirement.configuration_digest,
            )
            handle = self._resolver.resolve(binding)
        except Exception as exc:
            return (
                _diagnostic(
                    self._profile,
                    requirement,
                    ParticipantBindingDiagnosticCode.RUNTIME_UNAVAILABLE,
                    f"participant runtime unavailable: {type(exc).__name__}",
                ),
            )
        if handle.binding != binding:
            return (
                _diagnostic(
                    self._profile,
                    requirement,
                    ParticipantBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT,
                    "participant resolver returned a different runtime binding",
                ),
            )
        return ()

    def bind(self, requirement: ParticipantRequirement) -> ProjectParticipantBinding:
        diagnostics = self._preflight(requirement)
        if diagnostics:
            raise ParticipantProjectBindingError(diagnostics)
        try:
            runtime = self._runtime_selector(requirement)
            binding = ParticipantRuntimeBinding(
                role=requirement.role,
                implementation=requirement.implementation,
                runtime=runtime,
                configuration_digest=requirement.configuration_digest,
            )
            handle = self._resolver.resolve(binding)
        except Exception as exc:
            raise ParticipantProjectBindingError(
                (
                    _diagnostic(
                        self._profile,
                        requirement,
                        ParticipantBindingDiagnosticCode.RUNTIME_UNAVAILABLE,
                        f"participant runtime unavailable: {type(exc).__name__}",
                    ),
                )
            ) from exc
        if handle.binding != binding:
            raise ParticipantProjectBindingError(
                (
                    _diagnostic(
                        self._profile,
                        requirement,
                        ParticipantBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT,
                        "participant resolver returned a different runtime binding",
                    ),
                )
            )
        return ProjectParticipantBinding.from_runtime(
            requirement,
            self._profile,
            binding,
        )


__all__ = ["RuntimeParticipantProjectProvider", "RuntimeSelector"]
