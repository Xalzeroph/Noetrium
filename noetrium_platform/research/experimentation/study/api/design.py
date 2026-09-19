"""Author-level research design identities compiled by Experimentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.identity import ReplayLevel
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json

from .benchmark import BenchmarkTaskSet, TrialBudget
from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements
from .contracts import StudyConcurrencyPolicy
from .measurement import MeasurementProtocol

_HEX = frozenset("0123456789abcdef")


class BenchmarkAssignmentMode(StrEnum):
    """Granularity at which one frozen benchmark cut expands into Study assignments."""

    TASK = "task"
    CUT = "cut"



def _text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _sha(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return text

def _unique_strings(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise TypeError(f"{field_name} must be a non-empty tuple")
    if any(type(item) is not str or not item.strip() for item in value):
        raise TypeError(f"{field_name} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field_name} must be unique")
    return value
@dataclass(frozen=True, slots=True)
class FactorLevelSpec:
    level_id: str
    value: JsonValue
    control: bool = False
    level_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.level_id, "factor level level_id")
        if type(self.control) is not bool:
            raise TypeError("factor level control must be boolean")
        frozen = freeze_json(self.value)
        object.__setattr__(self, "value", frozen)
        object.__setattr__(
            self,
            "level_digest",
            canonical_digest(
                {"level_id": self.level_id, "value": frozen, "control": self.control}
            ),
        )


@dataclass(frozen=True, slots=True)
class StudyFactorSpec:
    factor_id: str
    levels: tuple[FactorLevelSpec, ...]
    factor_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.factor_id, "study factor factor_id")
        if type(self.levels) is not tuple or not self.levels:
            raise TypeError("study factor levels must be a non-empty tuple")
        if any(type(item) is not FactorLevelSpec for item in self.levels):
            raise TypeError("study factor levels must contain FactorLevelSpec")
        ids = tuple(item.level_id for item in self.levels)
        if len(ids) != len(set(ids)):
            raise ValueError("study factor level ids must be unique")
        object.__setattr__(
            self,
            "factor_digest",
            canonical_digest(
                {
                    "factor_id": self.factor_id,
                    "levels": tuple(item.level_digest for item in self.levels),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class FactorSelection:
    factor_id: str
    level_id: str
    level_digest: str

    def __post_init__(self) -> None:
        _text(self.factor_id, "factor selection factor_id")
        _text(self.level_id, "factor selection level_id")
        _sha(self.level_digest, "factor selection level_digest")

@dataclass(frozen=True, slots=True)
class StudyIntervention:
    intervention_id: str
    selections: tuple[FactorSelection, ...]
    intervention_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.intervention_id, "study intervention intervention_id")
        if type(self.selections) is not tuple:
            raise TypeError("study intervention selections must be a tuple")
        if any(type(item) is not FactorSelection for item in self.selections):
            raise TypeError("study intervention selections must contain FactorSelection")
        ids = tuple(item.factor_id for item in self.selections)
        if len(ids) != len(set(ids)):
            raise ValueError("study intervention factors must be unique")
        if self.selections != tuple(sorted(self.selections, key=lambda item: item.factor_id)):
            raise ValueError("study intervention selections must be canonically ordered")
        object.__setattr__(
            self,
            "intervention_digest",
            canonical_digest(
                {
                    "intervention_id": self.intervention_id,
                    "selections": self.selections,
                }
            ),
        )

    @property
    def control(self) -> bool:
        return self.intervention_id == "control"

@dataclass(frozen=True, slots=True)
class ResearchRevision:
    revision_id: str
    change_digest: str
    parent_revision_digest: str | None = None
    revision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.revision_id, "research revision revision_id")
        _sha(self.change_digest, "research revision change_digest")
        if self.parent_revision_digest is not None:
            _sha(self.parent_revision_digest, "research revision parent_revision_digest")
        object.__setattr__(
            self,
            "revision_digest",
            canonical_digest(
                {
                    "revision_id": self.revision_id,
                    "change_digest": self.change_digest,
                    "parent_revision_digest": self.parent_revision_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ParticipantSchedule:
    waves: tuple[tuple[str, ...], ...]
    schedule_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.waves) is not tuple or not self.waves:
            raise TypeError("participant schedule waves must be a non-empty tuple")
        roles: list[str] = []
        for wave in self.waves:
            if type(wave) is not tuple or not wave:
                raise TypeError("participant schedule wave must be a non-empty tuple")
            if any(type(role) is not str or not role.strip() for role in wave):
                raise TypeError("participant schedule roles must be non-empty strings")
            if len(wave) != len(set(wave)):
                raise ValueError("participant schedule wave roles must be unique")
            roles.extend(wave)
        if len(roles) != len(set(roles)):
            raise ValueError("participant schedule roles may appear only once")
        object.__setattr__(self, "schedule_digest", canonical_digest(self.waves))


@dataclass(frozen=True, slots=True)
class StudyExecutionPolicy:
    """Complete execution semantics for one scientific Study.

    Trial budget, replay guarantee and concurrency are one identity-bearing
    policy. None of them may be inferred by authoring helpers.
    """

    trial_budget: TrialBudget
    replay_level: ReplayLevel
    concurrency_policy: StudyConcurrencyPolicy
    policy_digest: str = field(init=False)

    @classmethod
    def serial_shared_v1(
        cls,
        *,
        trial_budget: TrialBudget,
        replay_level: ReplayLevel,
        repetition_timeout_seconds: float,
    ) -> "StudyExecutionPolicy":
        """Stable serial/shared preset with an explicit replay guarantee."""
        return cls(
            trial_budget=trial_budget,
            replay_level=replay_level,
            concurrency_policy=StudyConcurrencyPolicy.serial_shared_v1(
                repetition_timeout_seconds=repetition_timeout_seconds
            ),
        )

    def __post_init__(self) -> None:
        if type(self.trial_budget) is not TrialBudget:
            raise TypeError("study execution policy trial_budget must be TrialBudget")
        if not isinstance(self.replay_level, ReplayLevel):
            raise TypeError("study execution policy replay_level must be ReplayLevel")
        if type(self.concurrency_policy) is not StudyConcurrencyPolicy:
            raise TypeError(
                "study execution policy concurrency_policy must be StudyConcurrencyPolicy"
            )
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest(
                {
                    "trial_budget": self.trial_budget.budget_digest,
                    "replay_level": self.replay_level.value,
                    "concurrency_policy": self.concurrency_policy,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchStudyDefinition:
    project_id: str
    experiment_id: str
    study_id: str
    workload_id: str
    factors: tuple[StudyFactorSpec, ...]
    seeds: tuple[str, ...]
    repetitions: int
    measurement_protocol: MeasurementProtocol
    benchmark: BenchmarkTaskSet
    benchmark_split_id: str | None
    binding_requirements: ResearchBindingRequirements
    trial_protocol_identity: ExperimentTrialProtocolIdentity
    revision: ResearchRevision | None
    execution_policy: StudyExecutionPolicy
    benchmark_assignment_mode: BenchmarkAssignmentMode = BenchmarkAssignmentMode.TASK
    scientific_design_digest: str = field(init=False)
    participant_design_digest: str = field(init=False)
    binding_requirement_digest: str = field(init=False)
    execution_policy_digest: str = field(init=False)
    definition_digest: str = field(init=False)

    def __post_init__(self) -> None:
        """Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is total factors, factor levels, seeds, requirements and benchmark references; nested syntax only traverses disjoint child collections once.
        """
        for field_name, value in (("project_id", self.project_id), ("experiment_id", self.experiment_id), ("study_id", self.study_id), ("workload_id", self.workload_id)):
            _text(value, f"research study {field_name}")
        if type(self.factors) is not tuple or any(type(item) is not StudyFactorSpec for item in self.factors):
            raise TypeError("research study factors must be a tuple of StudyFactorSpec")
        factor_ids = tuple(item.factor_id for item in self.factors)
        if len(factor_ids) != len(set(factor_ids)):
            raise ValueError("research study factor ids must be unique")
        for factor in self.factors:
            if sum(level.control for level in factor.levels) > 1:
                raise ValueError("research study factor may declare at most one control level")
        _unique_strings(self.seeds, "research study seeds")
        if type(self.repetitions) is not int or self.repetitions <= 0:
            raise ValueError("research study repetitions must be a positive integer")
        if type(self.measurement_protocol) is not MeasurementProtocol:
            raise TypeError("research study measurement_protocol must be MeasurementProtocol")
        if type(self.benchmark) is not BenchmarkTaskSet:
            raise TypeError("research study benchmark must be BenchmarkTaskSet")
        if self.benchmark_split_id is not None:
            _text(self.benchmark_split_id, "research study benchmark_split_id")
            self.benchmark.selected_tasks(self.benchmark_split_id)
        if type(self.binding_requirements) is not ResearchBindingRequirements:
            raise TypeError("research study binding_requirements must be ResearchBindingRequirements")
        if type(self.trial_protocol_identity) is not ExperimentTrialProtocolIdentity:
            raise TypeError("research study trial_protocol_identity must be ExperimentTrialProtocolIdentity")
        if self.revision is not None and type(self.revision) is not ResearchRevision:
            raise TypeError("research study revision must be ResearchRevision or None")
        if type(self.execution_policy) is not StudyExecutionPolicy:
            raise TypeError("research study execution_policy must be StudyExecutionPolicy")
        if not isinstance(self.benchmark_assignment_mode, BenchmarkAssignmentMode):
            raise TypeError(
                "research study benchmark_assignment_mode must be BenchmarkAssignmentMode"
            )
        scientific = canonical_digest({"project_id": self.project_id, "experiment_id": self.experiment_id, "study_id": self.study_id, "workload_id": self.workload_id, "factors": tuple(item.factor_digest for item in self.factors), "seeds": self.seeds, "repetitions": self.repetitions, "measurement_semantics": self.measurement_protocol.semantic_digest, "benchmark_cut": self.benchmark.cut_digest, "benchmark_split_id": self.benchmark_split_id, "benchmark_assignment_mode": self.benchmark_assignment_mode.value, "trial_protocol": self.trial_protocol_identity.digest()})
        participant = canonical_digest(tuple(row.requirement_digest for row in self.binding_requirements.participants))
        binding_requirement = self.binding_requirements.requirements_digest
        execution = self.execution_policy.policy_digest
        object.__setattr__(self, "scientific_design_digest", scientific)
        object.__setattr__(self, "participant_design_digest", participant)
        object.__setattr__(self, "binding_requirement_digest", binding_requirement)
        object.__setattr__(self, "execution_policy_digest", execution)
        object.__setattr__(self, "definition_digest", canonical_digest({"scientific_design": scientific, "participant_design": participant, "binding_requirements": binding_requirement, "execution_policy": execution}))


__all__ = [
    "BenchmarkAssignmentMode",
    "FactorLevelSpec",
    "FactorSelection",
    "ParticipantSchedule",
    "ResearchRevision",
    "ResearchStudyDefinition",
    "StudyExecutionPolicy",
    "StudyFactorSpec",
    "StudyIntervention",
]
