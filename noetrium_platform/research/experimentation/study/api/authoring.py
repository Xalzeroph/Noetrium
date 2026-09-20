"""Declarative paper-facing Study authoring.

This module is intentionally smaller than the compiler IR. Authors declare
paper concepts; the constructor lowers them immediately into the canonical
ResearchStudyDefinition consumed by the research compiler.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.research.experimentation.binding import (
    ResearchBindingRequirements,
    ResearchModelRoleRequirement,
    ResearchParticipantRequirement,
)
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage, ReplayLevel

from .benchmark import BenchmarkTaskSet, TrialBudget
from .design import (
    BenchmarkAssignmentMode,
    ResearchRevision,
    ResearchStudyDefinition,
    StudyExecutionPolicy,
    StudyFactorSpec,
)
from .contracts import StudyConcurrencyPolicy
from .measurement import MeasurementDefinition, MeasurementProtocol


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _tokens(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    rows = tuple(_text(item, field) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return rows


@dataclass(frozen=True, slots=True)
class StudyParticipant:
    """Paper-facing declaration of one scientific participant.

    The author names scientific identity and requirements only. Session runtime,
    provider, endpoint and proof objects are compiler/runtime concerns.
    """

    role: str
    kind: str
    implementation: str
    treatment: str
    capabilities: tuple[str, ...] = ()
    configurations: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.role, "study participant role")
        _text(self.kind, "study participant kind")
        _text(self.implementation, "study participant implementation")
        _text(self.treatment, "study participant treatment")
        object.__setattr__(
            self, "capabilities", _tokens(self.capabilities, "study participant capabilities")
        )
        object.__setattr__(
            self,
            "configurations",
            _tokens(self.configurations, "study participant configurations"),
        )
        object.__setattr__(
            self, "depends_on", _tokens(self.depends_on, "study participant dependencies")
        )
        if self.role in self.depends_on:
            raise ValueError("study participant cannot depend on itself")

    def requirement(self) -> ResearchParticipantRequirement:
        return ResearchParticipantRequirement(
            role=self.role,
            participant_kind=self.kind,
            method_id=self.implementation,
            treatment_id=self.treatment,
            capability_requirement_ids=self.capabilities,
            configuration_ref_ids=self.configurations,
            depends_on_roles=self.depends_on,
        )


@dataclass(frozen=True, slots=True)
class StudyModel:
    """One named model responsibility in the paper-facing Study declaration."""

    requirement: str
    prompt: str | None = None
    usage: ModelRoleUsage = ModelRoleUsage.EXECUTION
    required: bool = True
    max_bindings: int | None = 1

    def __post_init__(self) -> None:
        _text(self.requirement, "study model requirement")
        if self.prompt is not None:
            _text(self.prompt, "study model prompt")
        if not isinstance(self.usage, ModelRoleUsage):
            raise TypeError("study model usage must be ModelRoleUsage")
        if type(self.required) is not bool:
            raise TypeError("study model required must be boolean")
        if self.max_bindings is not None and (
            type(self.max_bindings) is not int or self.max_bindings <= 0
        ):
            raise ValueError("study model max_bindings must be positive or None")

    def requirement_for(self, role: str) -> ResearchModelRoleRequirement:
        return ResearchModelRoleRequirement(
            role=role,
            requirement_id=self.requirement,
            prompt_configuration_id=self.prompt,
            usage=self.usage,
            required=self.required,
            max_bindings=self.max_bindings,
        )


class Study:
    """Compact declaration compiled to the canonical typed research protocol.

    Common-path authors declare benchmark, participants, model responsibilities,
    measurements, repetitions and limits. Provider bindings, runtime identities,
    proof objects and execution plans are deliberately absent from this surface.
    """

    def __init__(
        self,
        *,
        project_id: str,
        study_id: str,
        benchmark: BenchmarkTaskSet,
        method: StudyParticipant,
        models: Mapping[str, str | StudyModel],
        measurements: MeasurementProtocol | tuple[MeasurementDefinition, ...],
        trial: ExperimentTrialProtocolIdentity,
        repetitions: int,
        seeds: tuple[str, ...],
        limits: TrialBudget,
        measurements: MeasurementProtocol | tuple[MeasurementDefinition, ...] | None = None,
        benchmark_split_id: str | None = None,
        benchmark_assignment_mode: BenchmarkAssignmentMode = BenchmarkAssignmentMode.TASK,
        experiment_id: str | None = None,
        workload_id: str = "method-program",
        trial_provider_requirement_id: str = "trial.method-program",
        replay_level: ReplayLevel = ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds: float = 3600.0,
        concurrency_policy: StudyConcurrencyPolicy | None = None,
        factors: tuple[StudyFactorSpec, ...] = (),
        participants: tuple[StudyParticipant, ...] = (),
        revision: ResearchRevision | None = None,
    ) -> None:
        if type(method) is not StudyParticipant:
            raise TypeError("Study method must be StudyParticipant")
        if type(participants) is not tuple or any(
            type(row) is not StudyParticipant for row in participants
        ):
            raise TypeError("Study participants must contain StudyParticipant")
        participant_specs = (method,) + participants
        participant_roles = tuple(row.role for row in participant_specs)
        if len(participant_roles) != len(set(participant_roles)):
            raise ValueError("Study participant roles must be unique")
        known_roles = set(participant_roles)
        if any(
            dependency not in known_roles
            for participant in participant_specs
            for dependency in participant.depends_on
        ):
            raise ValueError("Study participant dependency is undeclared")

        if not isinstance(models, Mapping):
            raise TypeError("Study models must be a mapping")
        model_rows: list[ResearchModelRoleRequirement] = []
        for role, value in models.items():
            _text(role, "Study model role")
            spec = StudyModel(value) if type(value) is str else value
            if type(spec) is not StudyModel:
                raise TypeError("Study model values must be requirement ids or StudyModel")
            model_rows.append(spec.requirement_for(role))

        if type(measurements) is MeasurementProtocol:
            measurement_protocol = measurements
        elif type(measurements) is tuple and measurements and all(
            type(row) is MeasurementDefinition for row in measurements
        ):
            measurement_protocol = MeasurementProtocol(
                f"{study_id}.measurements",
                tuple(sorted(measurements, key=lambda row: row.measurement_id)),
            )
        else:
            raise TypeError(
                "Study measurements must be MeasurementProtocol or a non-empty "
                "tuple of MeasurementDefinition"
            )

        if type(limits) is not TrialBudget:
            raise TypeError("Study limits must be TrialBudget")
        if type(seeds) is not tuple or not seeds:
            raise TypeError("Study seeds must be a non-empty tuple")
        if any(type(seed) is not str or not seed.strip() for seed in seeds):
            raise TypeError("Study seeds must contain non-empty strings")
        if len(seeds) != len(set(seeds)):
            raise ValueError("Study seeds must be unique")
        if type(repetitions) is not int or repetitions <= 0:
            raise ValueError("Study repetitions must be positive")
        if not isinstance(replay_level, ReplayLevel):
            raise TypeError("Study replay_level must be ReplayLevel")

        if concurrency_policy is not None and type(concurrency_policy) is not StudyConcurrencyPolicy:
            raise TypeError("Study concurrency_policy must be StudyConcurrencyPolicy or None")
        policy = StudyExecutionPolicy(
            trial_budget=limits,
            replay_level=replay_level,
            concurrency_policy=(
                concurrency_policy
                or StudyConcurrencyPolicy.serial_shared_v1(
                    repetition_timeout_seconds=repetition_timeout_seconds
                )
            ),
        )
        requirements = ResearchBindingRequirements(
            trial_provider_requirement_id=trial_provider_requirement_id,
            participants=tuple(
                sorted(
                    (participant.requirement() for participant in participant_specs),
                    key=lambda row: row.role,
                )
            ),
            model_roles=tuple(sorted(model_rows, key=lambda row: row.role)),
        )
        self._definition = ResearchStudyDefinition(
            project_id=project_id,
            experiment_id=experiment_id or study_id,
            study_id=study_id,
            workload_id=workload_id,
            factors=tuple(sorted(factors, key=lambda row: row.factor_id)),
            seeds=seeds,
            repetitions=repetitions,
            measurement_protocol=measurement_protocol,
            benchmark=benchmark,
            benchmark_split_id=benchmark_split_id,
            binding_requirements=requirements,
            trial_protocol_identity=trial,
            revision=revision,
            execution_policy=policy,
            benchmark_assignment_mode=benchmark_assignment_mode,
        )

    @property
    def definition(self) -> ResearchStudyDefinition:
        return self._definition

    def build(self) -> ResearchStudyDefinition:
        return self._definition


@dataclass(frozen=True, slots=True)
class AgentStudySpec:
    """Common-path authoring for one method-program study.

    This removes participant/model/seed boilerplate without hiding scientific
    identities. Authors still supply the benchmark, trial protocol and budget;
    multi-participant or otherwise non-standard studies use Study directly.
    """

    project_id: str
    study_id: str
    method_id: str
    model: str | StudyModel
    measurements: MeasurementProtocol | tuple[MeasurementDefinition, ...] | None = None
    treatment: str = "full"
    participant_kind: str = "paper_method_program"
    benchmark_ids: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    configurations: tuple[str, ...] = ()
    model_role: str = "agent_model"

    def __post_init__(self) -> None:
        _text(self.project_id, "agent study project_id")
        _text(self.study_id, "agent study study_id")
        _text(self.method_id, "agent study method_id")
        _text(self.treatment, "agent study treatment")
        _text(self.participant_kind, "agent study participant_kind")
        _text(self.model_role, "agent study model_role")
        if type(self.model) is str:
            _text(self.model, "agent study model")
        elif type(self.model) is not StudyModel:
            raise TypeError("agent study model must be a requirement id or StudyModel")
        if self.measurements is None:
            pass
        elif type(self.measurements) is MeasurementProtocol:
            pass
        elif type(self.measurements) is tuple and self.measurements and all(
            type(row) is MeasurementDefinition for row in self.measurements
        ):
            pass
        else:
            raise TypeError(
                "agent study measurements must be None, MeasurementProtocol or a "
                "non-empty tuple of MeasurementDefinition"
            )
        object.__setattr__(
            self,
            "benchmark_ids",
            _tokens(self.benchmark_ids, "agent study benchmark ids"),
        )
        object.__setattr__(
            self,
            "capabilities",
            _tokens(self.capabilities, "agent study capabilities"),
        )
        object.__setattr__(
            self,
            "configurations",
            _tokens(self.configurations, "agent study configurations"),
        )

    def build(
        self,
        benchmark: BenchmarkTaskSet,
        *,
        trial: ExperimentTrialProtocolIdentity,
        limits: TrialBudget,
        benchmark_split_id: str | None = None,
        repetitions: int = 1,
        seeds: tuple[str, ...] | None = None,
        benchmark_assignment_mode: BenchmarkAssignmentMode = BenchmarkAssignmentMode.TASK,
        experiment_id: str | None = None,
        workload_id: str = "method-program",
        trial_provider_requirement_id: str = "trial.method-program",
        replay_level: ReplayLevel = ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds: float = 3600.0,
        concurrency_policy: StudyConcurrencyPolicy | None = None,
        factors: tuple[StudyFactorSpec, ...] = (),
        revision: ResearchRevision | None = None,
    ) -> ResearchStudyDefinition:
        if not isinstance(benchmark, BenchmarkTaskSet):
            raise TypeError("agent study benchmark must be BenchmarkTaskSet")
        resolved_measurements = self.measurements if measurements is None else measurements
        if resolved_measurements is None:
            raise ValueError("agent study measurements must be declared before build")
        if self.benchmark_ids and benchmark.benchmark_id not in self.benchmark_ids:
            raise ValueError(
                f"benchmark {benchmark.benchmark_id!r} is outside declared agent study "
                f"benchmarks {self.benchmark_ids!r}"
            )
        if seeds is None:
            if type(repetitions) is not int or repetitions <= 0:
                raise ValueError("agent study repetitions must be positive")
            seeds = tuple(f"repetition-{index}" for index in range(repetitions))
        return Study(
            project_id=self.project_id,
            study_id=self.study_id,
            benchmark=benchmark,
            benchmark_split_id=benchmark_split_id,
            method=StudyParticipant(
                role="agent",
                kind=self.participant_kind,
                implementation=self.method_id,
                treatment=self.treatment,
                capabilities=self.capabilities,
                configurations=self.configurations,
            ),
            models={self.model_role: self.model},
            measurements=resolved_measurements,
            trial=trial,
            repetitions=repetitions,
            seeds=seeds,
            limits=limits,
            benchmark_assignment_mode=benchmark_assignment_mode,
            experiment_id=experiment_id,
            workload_id=workload_id,
            trial_provider_requirement_id=trial_provider_requirement_id,
            replay_level=replay_level,
            repetition_timeout_seconds=repetition_timeout_seconds,
            concurrency_policy=concurrency_policy,
            factors=factors,
            revision=revision,
        ).build()


__all__ = ["AgentStudySpec", "Study", "StudyModel", "StudyParticipant"]
