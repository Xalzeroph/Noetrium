from __future__ import annotations

"""Derived execution-view ProjectManifest composition.

The filesystem ProjectManifest remains project identity/tool provenance. Scientific
requirements are derived from the frozen ResearchProgram + ResearchStudyDefinition,
so downstream projects never repeat Method/Study capability declarations.
"""

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectConfigurationReference,
    ProjectManifest,
    ProjectMethodRequirement,
    ProjectProviderBinding,
)
from noetrium_platform.product.research_os import ResearchDefinitionKind, ResearchProgram
from noetrium_platform.research.experimentation.api import ResearchStudyDefinition

from .research_binding_authority import (
    ResearchProjectManifestRequirement,
    ResearchProjectManifestResolverPort,
)
from .research_method_participant_binding import (
    exact_method_programs,
    exact_method_requirement_implementation_digest,
)

_AUTO_WORKLOAD_PROVIDER = "noetrium.auto.workload"
_PROVIDER_VERSION = "1"


def _requirement_parts(requirement_id: str) -> tuple[str, str]:
    if type(requirement_id) is not str or not requirement_id.strip():
        raise ValueError("research capability requirement id must be non-empty")
    if "." in requirement_id:
        namespace, name = requirement_id.split(".", 1)
        return namespace, name
    return "research", requirement_id


def _capability_requirement(
    requirement_id: str,
    *,
    program_digest: str,
    binding_requirement_digest: str,
) -> ProjectCapabilityRequirement:
    namespace, name = _requirement_parts(requirement_id)
    return ProjectCapabilityRequirement(
        requirement_id,
        namespace,
        name,
        1,
        canonical_digest(
            {
                "schema": "noetrium.derived-capability-requirement.v1",
                "requirement_id": requirement_id,
                "program_digest": program_digest,
                "binding_requirement_digest": binding_requirement_digest,
            }
        ),
    )


def derive_research_project_manifest(
    base: ProjectManifest,
    program: ResearchProgram,
    definition: ResearchStudyDefinition,
) -> ProjectManifest:
    """Derive the exact execution-view manifest required by one Study."""

    if not isinstance(base, ProjectManifest):
        raise TypeError("derived research manifest requires ProjectManifest base")
    if type(program) is not ResearchProgram:
        raise TypeError("derived research manifest requires ResearchProgram")
    if type(definition) is not ResearchStudyDefinition:
        raise TypeError(
            "derived research manifest requires ResearchStudyDefinition"
        )
    if base.project.identity.project_id != definition.project_id:
        raise ValueError(
            "derived research manifest project identity differs from Study"
        )

    requirement = ResearchProjectManifestRequirement.from_study(definition)
    program_digest = program.program_digest
    capabilities = tuple(
        _capability_requirement(
            requirement_id,
            program_digest=program_digest,
            binding_requirement_digest=definition.binding_requirement_digest,
        )
        for requirement_id in requirement.capability_requirement_ids
    )

    trial_requirement = definition.binding_requirements.trial_provider_requirement_id
    provider_bindings = ()
    if trial_requirement in requirement.capability_requirement_ids:
        provider_bindings = (
            ProjectProviderBinding(
                "auto.trial",
                trial_requirement,
                _AUTO_WORKLOAD_PROVIDER,
                _PROVIDER_VERSION,
                canonical_digest(
                    {
                        "schema": "noetrium.derived-workload-trial-provider.v1",
                        "program_digest": program_digest,
                        "study_digest": definition.definition_digest,
                    }
                ),
            ),
        )

    participant_by_key = {
        (row.method_id, row.treatment_id): row
        for row in definition.binding_requirements.participants
    }
    methods: list[ProjectMethodRequirement] = []
    for method_id, treatment_id in requirement.method_requirement_keys:
        participant = participant_by_key.get((method_id, treatment_id))
        if participant is None:
            raise ValueError(
                "Study manifest method key has no participant requirement: "
                f"{method_id!r}/{treatment_id!r}"
            )
        methods.append(
            ProjectMethodRequirement(
                method_id,
                treatment_id,
                exact_method_requirement_implementation_digest(
                    program,
                    participant,
                ),
            )
        )

    configuration_definitions = {
        row.definition_id: row
        for row in program.definitions
        if row.kind is ResearchDefinitionKind.CONFIGURATION
    }
    configurations: list[ProjectConfigurationReference] = []
    for config_id in requirement.configuration_ref_ids:
        config_definition = configuration_definitions.get(config_id)
        if config_definition is None:
            raise LookupError(
                "ResearchProgram has no exact CONFIGURATION definition for "
                f"configuration_id={config_id!r}"
            )
        configurations.append(
            ProjectConfigurationReference(
                config_id,
                (
                    "research-program://"
                    + program_digest
                    + "/configuration/"
                    + config_id
                ),
                config_definition.definition_digest,
            )
        )

    return ProjectManifest(
        base.project,
        base.template_revision,
        base.provenance,
        capability_requirements=capabilities,
        provider_bindings=provider_bindings,
        method_requirements=tuple(methods),
        configuration_refs=tuple(configurations),
        study_ids=(definition.study_id,),
    )


@dataclass(frozen=True, slots=True)
class PortfolioDerivedProjectManifestResolver:
    """Resolve each Study to the unique ResearchProgram that owns its Methods."""

    base: ProjectManifest
    programs: tuple[ResearchProgram, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.base, ProjectManifest):
            raise TypeError("derived manifest resolver requires ProjectManifest")
        if (
            type(self.programs) is not tuple
            or not self.programs
            or any(type(row) is not ResearchProgram for row in self.programs)
        ):
            raise TypeError(
                "derived manifest resolver requires non-empty ResearchProgram tuple"
            )

    def program_for(self, definition: ResearchStudyDefinition) -> ResearchProgram:
        """Resolve the unique ResearchProgram owning one Study's Method closure."""
        if type(definition) is not ResearchStudyDefinition:
            raise TypeError("derived manifest program lookup requires ResearchStudyDefinition")
        required_method_ids = {
            row.method_id
            for row in definition.binding_requirements.participants
        }
        matches = tuple(
            program
            for program in self.programs
            if required_method_ids.issubset(
                set(exact_method_programs(program))
            )
        )
        if len(matches) != 1:
            raise LookupError(
                "Study does not resolve to exactly one ResearchProgram by Method "
                f"ownership: study={definition.study_id!r} matches="
                f"{tuple(row.program_id for row in matches)!r}"
            )
        return matches[0]

    def _program(self, definition: ResearchStudyDefinition) -> ResearchProgram:
        return self.program_for(definition)

    def resolve(self, definition: ResearchStudyDefinition) -> ProjectManifest:
        if type(definition) is not ResearchStudyDefinition:
            raise TypeError(
                "derived manifest resolver requires ResearchStudyDefinition"
            )
        return derive_research_project_manifest(
            self.base,
            self._program(definition),
            definition,
        )


assert isinstance(
    PortfolioDerivedProjectManifestResolver,
    type,
)

__all__ = [
    "PortfolioDerivedProjectManifestResolver",
    "derive_research_project_manifest",
]
