"""Experimentation identity semantics.

Static research identity is carried only by NoetriumUnit. Dynamic requests may
reference those immutable identities by digest, but do not own parallel facet
objects.
"""
from __future__ import annotations

from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit


class ModelRoleUsage(StrEnum):
    EXECUTION = "execution"
    EVALUATION = "evaluation"
    BOTH = "both"

    @property
    def affects_execution(self) -> bool:
        return self in {ModelRoleUsage.EXECUTION, ModelRoleUsage.BOTH}

    @property
    def affects_evaluation(self) -> bool:
        return self in {ModelRoleUsage.EVALUATION, ModelRoleUsage.BOTH}


class ReplayLevel(StrEnum):
    EXACT = "exact"
    CHECKPOINT = "checkpoint"
    OBSERVATIONAL = "observational"


RUN_RESEARCH_SEMANTICS_TRAIT = "research.run-semantics"


def _optional_digest(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return require_sha256(value, field)


def run_research_semantics_unit(
    *,
    research_plan_digest: str,
    study_plan_digest: str,
    measurement_protocol_digest: str,
    trial_protocol_digest: str,
    method_implementation_digest: str,
    intervention_digest: str | None,
    topology_digest: str | None,
    participant_schedule_digest: str | None,
    revision_digest: str | None,
    replay_level: ReplayLevel,
) -> NoetriumUnit:
    for field, value in (
        ("research_plan_digest", research_plan_digest),
        ("study_plan_digest", study_plan_digest),
        ("measurement_protocol_digest", measurement_protocol_digest),
        ("trial_protocol_digest", trial_protocol_digest),
        ("method_implementation_digest", method_implementation_digest),
    ):
        require_sha256(value, f"run research semantics {field}")
    if not isinstance(replay_level, ReplayLevel):
        raise TypeError("run research semantics replay_level must be ReplayLevel")
    return structure_unit(
        "run-semantics",
        traits=(RUN_RESEARCH_SEMANTICS_TRAIT,),
        parameters={
            "research_plan_digest": research_plan_digest,
            "study_plan_digest": study_plan_digest,
            "measurement_protocol_digest": measurement_protocol_digest,
            "trial_protocol_digest": trial_protocol_digest,
            "method_implementation_digest": method_implementation_digest,
            "intervention_digest": _optional_digest(
                intervention_digest,
                "run research semantics intervention_digest",
            ),
            "topology_digest": _optional_digest(
                topology_digest,
                "run research semantics topology_digest",
            ),
            "participant_schedule_digest": _optional_digest(
                participant_schedule_digest,
                "run research semantics participant_schedule_digest",
            ),
            "revision_digest": _optional_digest(
                revision_digest,
                "run research semantics revision_digest",
            ),
            "replay_level": replay_level.value,
        },
    )


def require_run_research_semantics(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(RUN_RESEARCH_SEMANTICS_TRAIT):
        raise TypeError("run research semantics must be research.run-semantics NoetriumUnit")
    return value


def run_research_semantics_value(value: NoetriumUnit, name: str):
    return require_run_research_semantics(value).parameters[name]


def run_research_checkpoint_compatibility_digest(value: NoetriumUnit) -> str:
    value = require_run_research_semantics(value)
    parameters = value.parameters
    return canonical_digest({
        "trial_protocol_digest": parameters["trial_protocol_digest"],
        "method_implementation_digest": parameters["method_implementation_digest"],
        "intervention_digest": parameters["intervention_digest"],
        "topology_digest": parameters["topology_digest"],
        "participant_schedule_digest": parameters["participant_schedule_digest"],
        "revision_digest": parameters["revision_digest"],
        "replay_level": parameters["replay_level"],
    })


__all__ = [
    "ModelRoleUsage",
    "RUN_RESEARCH_SEMANTICS_TRAIT",
    "ReplayLevel",
    "require_run_research_semantics",
    "run_research_checkpoint_compatibility_digest",
    "run_research_semantics_unit",
    "run_research_semantics_value",
]
