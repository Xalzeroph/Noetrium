"""Author requirements and proof-backed producer bindings for research compilation."""
from __future__ import annotations


from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from noetrium_platform.research.execution.api import (
    PARTICIPANT_GRAPH_TRAIT,
    PARTICIPANT_REQUIREMENT_TRAIT,
    participant_graph,
    participant_requirement,
    participant_requirement_capabilities,
    participant_requirement_configurations,
    participant_requirement_kind,
    participant_requirement_method_id,
    participant_requirement_role,
    participant_requirement_treatment_id,
    participant_roles,
    require_participant_requirement,
)
from noetrium_platform.research.execution.api import BindingProof, CompositionSubject
from noetrium_platform.research.execution.api import ProjectParticipantBinding
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.identity import ModelRoleUsage
from noetrium_platform.research.execution.api import (
    project_capability_requirement_id,
    project_configuration_reference_id,
    project_method_requirement_method_id,
    project_method_requirement_treatment_id,
    project_provider_binding_requirement_id,
    require_project_capability_requirement,
    require_project_configuration_reference,
    require_project_method_requirement,
    require_project_provider_binding,
)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _sha(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    return require_sha256(value, field_name)


def _unique_strings(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    if any(type(row) is not str or not row.strip() for row in value):
        raise TypeError(f"{field_name} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field_name} must be unique")
    return value


MODEL_ROLE_REQUIREMENT_TRAIT = "noetrium.model-role-requirement"
BINDING_REQUIREMENTS_TRAIT = "noetrium.binding-requirements"


def model_role_requirement(
    role: str,
    requirement_id: str,
    *,
    prompt_configuration_id: str | None = None,
    usage: ModelRoleUsage = ModelRoleUsage.EXECUTION,
    required: bool = True,
    max_bindings: int | None = 1,
    capability_id: str = "generation",
    required_capabilities: tuple[str, ...] = (),
    input_schema_id: str = "model.generation.request.v1",
    output_schema_id: str = "model.generation.response.v1",
    minimum_context_tokens: int = 1,
) -> NoetriumUnit:
    role = _text(role, "model role requirement role")
    requirement_id = _text(requirement_id, "model role requirement id")
    if prompt_configuration_id is not None:
        prompt_configuration_id = _text(
            prompt_configuration_id, "model role prompt configuration id"
        )
    if not isinstance(usage, ModelRoleUsage):
        raise TypeError("model role usage must be ModelRoleUsage")
    if type(required) is not bool:
        raise TypeError("model role required must be boolean")
    if max_bindings is not None and (
        type(max_bindings) is not int or max_bindings <= 0
    ):
        raise ValueError("model role max_bindings must be positive or None")
    capability_id = _text(capability_id, "model role capability_id")
    input_schema_id = _text(input_schema_id, "model role input_schema_id")
    output_schema_id = _text(output_schema_id, "model role output_schema_id")
    required_capabilities = _unique_strings(
        required_capabilities, "model role required capabilities"
    )
    if type(minimum_context_tokens) is not int or minimum_context_tokens <= 0:
        raise ValueError("model role minimum_context_tokens must be positive")
    if (
        capability_id not in {"generation", "structured-generation"}
        and prompt_configuration_id is not None
    ):
        raise ValueError(
            "non-generation model role must not carry prompt configuration"
        )
    return structure_unit(
        f"model-role-requirement:{role}",
        traits=(MODEL_ROLE_REQUIREMENT_TRAIT,),
        parameters={
            "role": role,
            "requirement_id": requirement_id,
            "prompt_configuration_id": prompt_configuration_id,
            "usage": usage.value,
            "required": required,
            "max_bindings": max_bindings,
            "capability_id": capability_id,
            "required_capabilities": required_capabilities,
            "input_schema_id": input_schema_id,
            "output_schema_id": output_schema_id,
            "minimum_context_tokens": minimum_context_tokens,
        },
    )


def require_model_role_requirement(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(MODEL_ROLE_REQUIREMENT_TRAIT)
    ):
        raise TypeError(
            "model role requirement must be noetrium.model-role-requirement Unit"
        )
    return value


def model_role_requirement_value(value: NoetriumUnit, name: str):
    require_model_role_requirement(value)
    return value.parameters[name]


def model_role_requirement_role(value: NoetriumUnit) -> str:
    return str(model_role_requirement_value(value, "role"))


def model_role_requirement_id(value: NoetriumUnit) -> str:
    return str(model_role_requirement_value(value, "requirement_id"))


def model_role_requirement_prompt(value: NoetriumUnit) -> str | None:
    raw = model_role_requirement_value(value, "prompt_configuration_id")
    return None if raw is None else str(raw)


def model_role_requirement_usage(value: NoetriumUnit) -> ModelRoleUsage:
    return ModelRoleUsage(str(model_role_requirement_value(value, "usage")))


def model_role_requirement_required(value: NoetriumUnit) -> bool:
    return bool(model_role_requirement_value(value, "required"))


def model_role_requirement_max_bindings(value: NoetriumUnit) -> int | None:
    raw = model_role_requirement_value(value, "max_bindings")
    return None if raw is None else int(raw)


def model_role_requirement_capability(value: NoetriumUnit) -> str:
    return str(model_role_requirement_value(value, "capability_id"))


def model_role_requirement_capabilities(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(model_role_requirement_value(value, "required_capabilities"))


def model_role_requirement_input_schema(value: NoetriumUnit) -> str:
    return str(model_role_requirement_value(value, "input_schema_id"))


def model_role_requirement_output_schema(value: NoetriumUnit) -> str:
    return str(model_role_requirement_value(value, "output_schema_id"))


def model_role_requirement_minimum_context(value: NoetriumUnit) -> int:
    return int(model_role_requirement_value(value, "minimum_context_tokens"))


def binding_requirements(
    trial_provider_requirement_id: str,
    *,
    participants: tuple[NoetriumUnit, ...] = (),
    model_roles: tuple[NoetriumUnit, ...] = (),
    participant_topology: NoetriumUnit | None = None,
) -> NoetriumUnit:
    trial_provider_requirement_id = _text(
        trial_provider_requirement_id, "trial provider requirement id"
    )
    if type(participants) is not tuple:
        raise TypeError("binding requirement participants must be tuple")
    for row in participants:
        require_participant_requirement(row)
    participant_role_ids = tuple(participant_requirement_role(row) for row in participants)
    if len(participant_role_ids) != len(set(participant_role_ids)):
        raise ValueError("binding requirement participant roles must be unique")
    topology = (
        participant_graph(participant_role_ids)
        if participant_topology is None
        else participant_topology
    )
    if set(participant_roles(topology)) != set(participant_role_ids):
        raise ValueError(
            "binding requirement participant graph must cover exactly the declared roles"
        )
    if type(model_roles) is not tuple:
        raise TypeError("binding requirement model roles must be tuple")
    for row in model_roles:
        require_model_role_requirement(row)
    ordered_model_roles = tuple(
        sorted(model_roles, key=model_role_requirement_role)
    )
    names = tuple(model_role_requirement_role(row) for row in ordered_model_roles)
    if len(names) != len(set(names)):
        raise ValueError("binding requirement model roles must be unique")
    return structure_unit(
        "binding-requirements",
        traits=(BINDING_REQUIREMENTS_TRAIT,),
        parameters={
            "trial_provider_requirement_id": trial_provider_requirement_id,
        },
        members=participants + ordered_model_roles + (topology,),
    )


def require_binding_requirements(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(BINDING_REQUIREMENTS_TRAIT)
    ):
        raise TypeError(
            "binding requirements must be noetrium.binding-requirements Unit"
        )
    return value


def binding_requirements_participants(
    value: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    require_binding_requirements(value)
    return tuple(
        row
        for row in value.members
        if row.has_trait(PARTICIPANT_REQUIREMENT_TRAIT)
    )


def binding_requirements_model_roles(
    value: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    require_binding_requirements(value)
    return tuple(
        row for row in value.members if row.has_trait(MODEL_ROLE_REQUIREMENT_TRAIT)
    )


def binding_requirements_topology(value: NoetriumUnit) -> NoetriumUnit:
    require_binding_requirements(value)
    rows = tuple(
        row
        for row in value.members
        if row.has_trait(PARTICIPANT_GRAPH_TRAIT)
    )
    if len(rows) != 1:
        raise ValueError("binding requirements require exactly one participant topology")
    return rows[0]


def binding_requirements_trial_provider(value: NoetriumUnit) -> str:
    require_binding_requirements(value)
    return str(value.parameters["trial_provider_requirement_id"])


def binding_requirements_model_role(
    value: NoetriumUnit, role: str
) -> NoetriumUnit:
    _text(role, "model role lookup")
    rows = tuple(
        row
        for row in binding_requirements_model_roles(value)
        if model_role_requirement_role(row) == role
    )
    if len(rows) != 1:
        raise KeyError(f"binding requirements have no unique model role: {role}")
    return rows[0]


@dataclass(frozen=True, slots=True)
class ResearchRequirementResolution:
    project_manifest_digest: str
    project_subject: CompositionSubject
    requirements_digest: str
    capability_requirements: tuple[NoetriumUnit, ...]
    method_requirements: tuple[NoetriumUnit, ...]
    configuration_refs: tuple[NoetriumUnit, ...]
    provider_bindings: tuple[NoetriumUnit, ...]

    resolution_digest: str = field(init=False)
    _capability_requirements_by_id: Mapping[
        str, NoetriumUnit
    ] = field(init=False, repr=False, compare=False)
    _method_requirements_by_key: Mapping[
        tuple[str, str], NoetriumUnit
    ] = field(init=False, repr=False, compare=False)
    _configuration_refs_by_id: Mapping[
        str, NoetriumUnit
    ] = field(init=False, repr=False, compare=False)
    _provider_bindings_by_requirement: Mapping[
        str, tuple[NoetriumUnit, ...]
    ] = field(init=False, repr=False, compare=False)
    _capability_requirement_ids: tuple[str, ...] = field(
        init=False, repr=False, compare=False
    )
    _method_requirement_keys: tuple[tuple[str, str], ...] = field(
        init=False, repr=False, compare=False
    )
    _configuration_ref_ids: tuple[str, ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _sha(self.project_manifest_digest, "requirement resolution project_manifest_digest")
        if not isinstance(self.project_subject, CompositionSubject):
            raise TypeError("requirement resolution project_subject must be CompositionSubject")
        _sha(self.requirements_digest, "requirement resolution requirements_digest")
        if type(self.capability_requirements) is not tuple:
            raise TypeError("resolved capability requirements must be Unit tuple")
        for row in self.capability_requirements:
            require_project_capability_requirement(row)
        if type(self.method_requirements) is not tuple:
            raise TypeError("resolved method requirements must be Unit tuple")
        for row in self.method_requirements:
            require_project_method_requirement(row)
        if type(self.configuration_refs) is not tuple:
            raise TypeError("resolved configuration refs must be Unit tuple")
        for row in self.configuration_refs:
            require_project_configuration_reference(row)
        if type(self.provider_bindings) is not tuple:
            raise TypeError("resolved provider bindings must be Unit tuple")
        for row in self.provider_bindings:
            require_project_provider_binding(row)
        capability_ids = tuple(project_capability_requirement_id(row) for row in self.capability_requirements)
        method_keys = tuple((project_method_requirement_method_id(row), project_method_requirement_treatment_id(row)) for row in self.method_requirements)
        config_ids = tuple(project_configuration_reference_id(row) for row in self.configuration_refs)
        object.__setattr__(self, "_capability_requirement_ids", capability_ids)
        object.__setattr__(self, "_method_requirement_keys", method_keys)
        object.__setattr__(self, "_configuration_ref_ids", config_ids)
        if len(capability_ids) != len(set(capability_ids)) or len(method_keys) != len(set(method_keys)) or len(config_ids) != len(set(config_ids)):
            raise ValueError("requirement resolution contains duplicate requirement identities")

        capability_id_set = set(capability_ids)
        if any(
            project_provider_binding_requirement_id(row) not in capability_id_set
            for row in self.provider_bindings
        ):
            raise ValueError("resolved provider binding names an unselected capability requirement")

        provider_index: dict[str, list[NoetriumUnit]] = {}
        for row in self.provider_bindings:
            provider_index.setdefault(project_provider_binding_requirement_id(row), []).append(row)
        object.__setattr__(
            self,
            "_capability_requirements_by_id",
            MappingProxyType({
                project_capability_requirement_id(row): row for row in self.capability_requirements
            }),
        )
        object.__setattr__(
            self,
            "_method_requirements_by_key",
            MappingProxyType({
                (project_method_requirement_method_id(row), project_method_requirement_treatment_id(row)): row
                for row in self.method_requirements
            }),
        )
        object.__setattr__(
            self,
            "_configuration_refs_by_id",
            MappingProxyType({
                project_configuration_reference_id(row): row for row in self.configuration_refs
            }),
        )
        object.__setattr__(
            self,
            "_provider_bindings_by_requirement",
            MappingProxyType({
                key: tuple(values) for key, values in provider_index.items()
            }),
        )
        object.__setattr__(self, "resolution_digest", canonical_digest({
            "project_manifest_digest": self.project_manifest_digest,
            "project_subject": self.project_subject.key,
            "requirements_digest": self.requirements_digest,
            "capability_requirements": tuple(row.unit_digest for row in self.capability_requirements),
            "method_requirements": tuple(row.unit_digest for row in self.method_requirements),
            "configuration_refs": tuple(row.unit_digest for row in self.configuration_refs),
            "provider_bindings": tuple(row.unit_digest for row in self.provider_bindings),
        }))

    @property
    def capability_requirement_ids(self) -> tuple[str, ...]:
        return self._capability_requirement_ids

    @property
    def method_requirement_keys(self) -> tuple[tuple[str, str], ...]:
        return self._method_requirement_keys

    @property
    def configuration_ref_ids(self) -> tuple[str, ...]:
        return self._configuration_ref_ids

    def capability_requirement(self, requirement_id: str) -> NoetriumUnit:
        try:
            return self._capability_requirements_by_id[requirement_id]
        except KeyError as exc:
            raise KeyError(
                f"resolved capability requirement is not unique: {requirement_id}"
            ) from exc

    def method_requirement(
        self, method_id: str, treatment_id: str
    ) -> NoetriumUnit:
        try:
            return self._method_requirements_by_key[(method_id, treatment_id)]
        except KeyError as exc:
            raise KeyError(
                "resolved method requirement is not unique: "
                f"{method_id}/{treatment_id}"
            ) from exc

    def configuration_ref(
        self, configuration_id: str
    ) -> NoetriumUnit:
        try:
            return self._configuration_refs_by_id[configuration_id]
        except KeyError as exc:
            raise KeyError(
                f"resolved configuration ref is not unique: {configuration_id}"
            ) from exc

    def provider_bindings_for(
        self, requirement_id: str
    ) -> tuple[NoetriumUnit, ...]:
        return self._provider_bindings_by_requirement.get(requirement_id, ())


@dataclass(frozen=True, slots=True)
class ResearchCapabilityBinding:
    requirement_id: str
    proof: BindingProof
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.requirement_id, "capability binding requirement_id")
        if not isinstance(self.proof, BindingProof):
            raise TypeError("capability binding proof must be BindingProof")
        object.__setattr__(self, "binding_digest", canonical_digest({
            "requirement_id": self.requirement_id,
            "proof_digest": self.proof.digest,
        }))


@dataclass(frozen=True, slots=True)
class ResearchParticipantBinding:
    role: str
    binding: ProjectParticipantBinding
    proof: BindingProof
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.role, "participant binding role")
        if not isinstance(self.binding, ProjectParticipantBinding):
            raise TypeError("participant binding must be ProjectParticipantBinding")
        if not isinstance(self.proof, BindingProof):
            raise TypeError("participant binding proof must be BindingProof")

        if self.binding.binding.role != self.role:
            raise ValueError("participant binding role drifted")
        if self.proof.requirement_digest.value != self.binding.requirement_digest:
            raise ValueError("participant binding proof requirement drifted")
        if self.proof.provider_identity != self.binding.provider_id:
            raise ValueError("participant binding proof provider drifted")
        if self.proof.provider_profile_digest.value != self.binding.provider_profile_digest:
            raise ValueError("participant binding proof profile drifted")
        expected_generation = f"participant-{self.binding.binding.runtime.digest()}"
        if self.proof.binding_generation != expected_generation:
            raise ValueError("participant binding proof generation drifted")
        object.__setattr__(self, "binding_digest", canonical_digest({
            "role": self.role,
            "domain_binding_digest": self.binding.digest(),
            "proof_digest": self.proof.digest,
        }))


@dataclass(frozen=True, slots=True)
class ResearchModelRoleBinding:
    """Static scientific Model-role binding over one MODEL NoetriumUnit.

    Runtime deployment, host placement, service generation and qualification
    are deliberately excluded. Those are dynamic Authority/Event facts and are
    closed only when execution first consumes this role.
    """

    requirement_id: str
    requirement_digest: str
    binding: NoetriumUnit
    proof: BindingProof
    role: str
    model_id: str
    prompt_generation_id: str | None
    prompt_digest: str | None
    capabilities: tuple[str, ...]
    member_index: int = 0
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.requirement_id, "model role binding requirement_id")
        _sha(self.requirement_digest, "model role binding requirement_digest")
        _text(self.role, "model role binding role")
        _text(self.model_id, "model role binding model_id")
        if type(self.member_index) is not int or self.member_index < 0:
            raise ValueError(
                "model role binding member_index must be a non-negative integer"
            )
        if type(self.binding) is not NoetriumUnit:
            raise TypeError("model binding must be NoetriumUnit")
        if not isinstance(self.proof, BindingProof):
            raise TypeError("model role binding proof must be BindingProof")
        if self.prompt_generation_id is None:
            if self.prompt_digest is not None:
                raise ValueError(
                    "model role binding prompt digest requires prompt generation"
                )
        else:
            _text(
                self.prompt_generation_id,
                "model role binding prompt_generation_id",
            )
            _sha(self.prompt_digest, "model role binding prompt_digest")
        capabilities = _unique_strings(
            tuple(sorted(self.capabilities)),
            "model role binding capabilities",
        )
        object.__setattr__(self, "capabilities", capabilities)
        if self.proof.requirement_digest.value != self.requirement_digest:
            raise ValueError("model role binding proof requirement drifted")

        model_definition_digest = self.binding.parameters.get(
            "model_definition_digest"
        )
        _sha(
            model_definition_digest,
            "model role binding model_definition_digest",
        )
        profile_digest = canonical_digest({
            "schema": "noetrium.research-model-binding.v2",
            "model_definition_digest": model_definition_digest,
            "model_id": self.model_id,
            "prompt_generation_id": self.prompt_generation_id,
            "prompt_digest": self.prompt_digest,
            "capabilities": capabilities,
        })
        if self.proof.provider_profile_digest.value != profile_digest:
            raise ValueError("model role binding proof profile drifted")
        if self.proof.binding_generation != "model-" + profile_digest[:24]:
            raise ValueError("model role binding proof generation drifted")
        object.__setattr__(self, "binding_digest", canonical_digest({
            "schema": "noetrium.research-model-role-binding.v2",
            "role": self.role,
            "member_index": self.member_index,
            "requirement_id": self.requirement_id,
            "requirement_digest": self.requirement_digest,
            "model_definition_digest": model_definition_digest,
            "model_id": self.model_id,
            "prompt_generation_id": self.prompt_generation_id,
            "prompt_digest": self.prompt_digest,
            "capabilities": capabilities,
            "proof_digest": self.proof.digest,
        }))


@dataclass(frozen=True, slots=True)
class ResearchBindingAssuranceGap:
    """Proof gap that limits scientific assurance without defining execution mode."""

    domain: str
    requirement_key: str
    requirement_digest: str
    diagnostic_digests: tuple[str, ...] = ()
    gap_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.domain, "binding assurance gap domain")
        _text(self.requirement_key, "binding assurance gap requirement_key")
        _sha(self.requirement_digest, "binding assurance gap requirement_digest")
        if type(self.diagnostic_digests) is not tuple:
            raise TypeError("binding assurance gap diagnostic_digests must be tuple")
        for digest in self.diagnostic_digests:
            _sha(digest, "binding assurance gap diagnostic digest")
        ordered = tuple(sorted(self.diagnostic_digests))
        if len(ordered) != len(set(ordered)):
            raise ValueError("binding assurance gap diagnostics must be unique")
        object.__setattr__(self, "diagnostic_digests", ordered)
        object.__setattr__(self, "gap_digest", canonical_digest({
            "domain": self.domain,
            "requirement_key": self.requirement_key,
            "requirement_digest": self.requirement_digest,
            "diagnostic_digests": ordered,
        }))


@dataclass(frozen=True, slots=True)
class ResearchBindingContribution:
    requirement_resolution_digest: str
    capability_bindings: tuple[ResearchCapabilityBinding, ...]
    participant_bindings: tuple[ResearchParticipantBinding, ...] = ()
    model_role_bindings: tuple[ResearchModelRoleBinding, ...] = ()
    assurance_gaps: tuple[ResearchBindingAssuranceGap, ...] = ()
    contribution_digest: str = field(init=False)
    _capability_bindings_by_requirement: Mapping[
        str, tuple[ResearchCapabilityBinding, ...]
    ] = field(init=False, repr=False, compare=False)
    _model_role_bindings_by_role: Mapping[
        str, tuple[ResearchModelRoleBinding, ...]
    ] = field(init=False, repr=False, compare=False)
    _assurance_gaps_by_key: Mapping[
        tuple[str, str], tuple[ResearchBindingAssuranceGap, ...]
    ] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _sha(self.requirement_resolution_digest, "binding contribution resolution digest")
        if type(self.capability_bindings) is not tuple or any(
            not isinstance(row, ResearchCapabilityBinding) for row in self.capability_bindings
        ):
            raise TypeError("binding contribution capability_bindings must be typed")
        capability_digests = tuple(row.binding_digest for row in self.capability_bindings)
        if len(capability_digests) != len(set(capability_digests)):
            raise ValueError("binding contribution capability proofs must be unique")
        if type(self.participant_bindings) is not tuple or any(
            not isinstance(row, ResearchParticipantBinding) for row in self.participant_bindings
        ):
            raise TypeError("binding contribution participant_bindings must be typed")
        participant_roles = tuple(row.role for row in self.participant_bindings)
        if len(participant_roles) != len(set(participant_roles)):
            raise ValueError("binding contribution participant roles must be unique")
        if type(self.model_role_bindings) is not tuple or any(
            not isinstance(row, ResearchModelRoleBinding) for row in self.model_role_bindings
        ):
            raise TypeError("binding contribution model_role_bindings must be typed")
        ordered_model_role_bindings = tuple(
            sorted(self.model_role_bindings, key=lambda row: (row.role, row.member_index))
        )
        object.__setattr__(self, "model_role_bindings", ordered_model_role_bindings)
        member_keys = tuple((row.role, row.member_index) for row in ordered_model_role_bindings)
        if len(member_keys) != len(set(member_keys)):
            raise ValueError("binding contribution model role members must be unique")
        if type(self.assurance_gaps) is not tuple or any(
            not isinstance(row, ResearchBindingAssuranceGap)
            for row in self.assurance_gaps
        ):
            raise TypeError("binding contribution assurance_gaps must be typed")
        ordered_gaps = tuple(sorted(self.assurance_gaps, key=lambda row: row.gap_digest))
        if len({row.gap_digest for row in ordered_gaps}) != len(ordered_gaps):
            raise ValueError("binding contribution assurance gaps must be unique")
        object.__setattr__(self, "assurance_gaps", ordered_gaps)

        capability_index: dict[str, list[ResearchCapabilityBinding]] = {}
        for row in self.capability_bindings:
            capability_index.setdefault(row.requirement_id, []).append(row)
        model_role_index: dict[str, list[ResearchModelRoleBinding]] = {}
        for row in ordered_model_role_bindings:
            model_role_index.setdefault(row.role, []).append(row)
        assurance_gap_index: dict[
            tuple[str, str], list[ResearchBindingAssuranceGap]
        ] = {}
        for row in ordered_gaps:
            assurance_gap_index.setdefault(
                (row.domain, row.requirement_digest), []
            ).append(row)
        object.__setattr__(
            self,
            "_capability_bindings_by_requirement",
            MappingProxyType({
                key: tuple(values) for key, values in capability_index.items()
            }),
        )
        object.__setattr__(
            self,
            "_model_role_bindings_by_role",
            MappingProxyType({
                key: tuple(values) for key, values in model_role_index.items()
            }),
        )
        object.__setattr__(
            self,
            "_assurance_gaps_by_key",
            MappingProxyType({
                key: tuple(values) for key, values in assurance_gap_index.items()
            }),
        )

        object.__setattr__(self, "contribution_digest", canonical_digest({
            "requirement_resolution_digest": self.requirement_resolution_digest,
            "capability_bindings": tuple(row.binding_digest for row in self.capability_bindings),
            "participant_bindings": tuple(row.binding_digest for row in self.participant_bindings),
            "model_role_bindings": tuple(row.binding_digest for row in ordered_model_role_bindings),
            "assurance_gaps": tuple(row.gap_digest for row in ordered_gaps),
        }))

    @property
    def binding_assurance_complete(self) -> bool:
        return not self.assurance_gaps

    def assurance_gaps_for(
        self, *, domain: str, requirement_digest: str
    ) -> tuple[ResearchBindingAssuranceGap, ...]:
        _text(domain, "binding assurance gap domain lookup")
        _sha(requirement_digest, "binding assurance gap requirement lookup")
        return self._assurance_gaps_by_key.get((domain, requirement_digest), ())

    def model_role_bindings_for(self, role: str) -> tuple[ResearchModelRoleBinding, ...]:
        _text(role, "model role binding lookup")
        return self._model_role_bindings_by_role.get(role, ())

    def model_role_binding(self, role: str) -> ResearchModelRoleBinding:
        matches = self.model_role_bindings_for(role)
        if len(matches) != 1:
            raise KeyError(f"binding contribution has no unique model binding for role {role}")
        return matches[0]

    def capability_bindings_for(self, requirement_id: str) -> tuple[ResearchCapabilityBinding, ...]:
        return self._capability_bindings_by_requirement.get(requirement_id, ())

    def capability_binding(self, requirement_id: str) -> ResearchCapabilityBinding:
        matches = self.capability_bindings_for(requirement_id)
        if len(matches) != 1:
            raise KeyError(f"binding contribution has no unique capability proof for {requirement_id}")
        return matches[0]


__all__ = [
    "binding_requirements",
    "binding_requirements_model_role",
    "binding_requirements_model_roles",
    "binding_requirements_participants",
    "binding_requirements_topology",
    "binding_requirements_trial_provider",
    "model_role_requirement",
    "model_role_requirement_capabilities",
    "model_role_requirement_capability",
    "model_role_requirement_id",
    "model_role_requirement_input_schema",
    "model_role_requirement_max_bindings",
    "model_role_requirement_minimum_context",
    "model_role_requirement_output_schema",
    "model_role_requirement_prompt",
    "model_role_requirement_required",
    "model_role_requirement_role",
    "model_role_requirement_usage",
    "participant_requirement",
    "participant_requirement_capabilities",
    "participant_requirement_configurations",
    "participant_requirement_kind",
    "participant_requirement_method_id",
    "participant_requirement_role",
    "participant_requirement_treatment_id",
    "require_binding_requirements",
    "require_model_role_requirement",
    "require_participant_requirement",
    "ResearchBindingAssuranceGap",
    "ResearchBindingContribution",
    "ResearchCapabilityBinding",
    "ResearchModelRoleBinding",
    "ResearchParticipantBinding",
    "ResearchRequirementResolution",
]
