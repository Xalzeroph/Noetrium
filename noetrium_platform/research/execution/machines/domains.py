"""Domain authoring surfaces for universal research Machines.

These builders fix a semantic domain while compiling to the single
ResearchProgram IR. Paper-private operations remain legal through custom(),
so new research semantics never require a kernel enum or a new runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import JsonObject, MachineKind
from .program import ResearchProgram, ResearchProgramBuilder


class RuntimeConcern(StrEnum):
    TURN = "turn"
    EVENT = "event"
    CONTEXT = "context"
    COMMUNICATION = "communication"
    LOGICAL_SCHEDULING = "logical_scheduling"
    SYNCHRONIZATION = "synchronization"
    CAPABILITY_MEDIATION = "capability_mediation"
    VISIBILITY = "visibility"
    RECOVERY = "recovery"
    INTERVENTION = "intervention"


class ParticipantConcern(StrEnum):
    ROLE = "role"
    TURN = "turn"
    STATE = "state"
    PLANNING = "planning"
    ACTION = "action"
    INTERACTION = "interaction"
    TOOL_USE = "tool_use"
    INTERRUPTION = "interruption"
    RECOVERY = "recovery"
    VISIBILITY = "visibility"


class MemoryConcern(StrEnum):
    WRITE = "write"
    RETRIEVAL = "retrieval"
    INDEX = "index"
    TRUST = "trust"
    CONSOLIDATION = "consolidation"
    RETENTION = "retention"
    PROJECTION = "projection"
    RECOVERY = "recovery"


class EnvironmentConcern(StrEnum):
    OBSERVATION = "observation"
    TRANSITION = "transition"
    QUERY = "query"
    BRANCHING = "branching"
    RESET = "reset"
    RECONCILIATION = "reconciliation"
    RECOVERY = "recovery"
    VISIBILITY = "visibility"


class EvaluationConcern(StrEnum):
    INPUT = "input"
    VALIDATION = "validation"
    SCORING = "scoring"
    COMPARISON = "comparison"
    AGGREGATION = "aggregation"
    JUDGMENT = "judgment"
    CALIBRATION = "calibration"
    FINALIZATION = "finalization"


class OptimizationConcern(StrEnum):
    PROPOSAL = "proposal"
    MUTATION = "mutation"
    EVALUATION = "evaluation"
    SELECTION = "selection"
    GENERATION = "generation"
    BUDGET = "budget"
    TERMINATION = "termination"
    RECOVERY = "recovery"


class ExperimentConcern(StrEnum):
    DESIGN = "design"
    ASSIGNMENT = "assignment"
    SCHEDULING = "scheduling"
    OBSERVATION = "observation"
    ADAPTATION = "adaptation"
    REPLICATION = "replication"
    AGGREGATION = "aggregation"
    STOPPING = "stopping"
    FINALIZATION = "finalization"


class RunConcern(StrEnum):
    LIFECYCLE = "lifecycle"
    CYCLE = "cycle"
    CHECKPOINT = "checkpoint"
    CONTROL = "control"
    RECOVERY = "recovery"
    EVIDENCE = "evidence"
    FINALIZATION = "finalization"


_KIND_PREFIX = {
    MachineKind.RUNTIME: "runtime",
    MachineKind.PARTICIPANT: "participant",
    MachineKind.ENVIRONMENT: "environment",
    MachineKind.MEMORY: "memory",
    MachineKind.EVALUATION: "evaluation",
    MachineKind.OPTIMIZATION: "optimization",
    MachineKind.EXPERIMENT: "experiment",
    MachineKind.RUN: "run",
}


@dataclass(slots=True)
class DomainProgramBuilder:
    _builder: ResearchProgramBuilder
    kind: MachineKind

    @classmethod
    def create(
        cls, *, program_id: str, kind: MachineKind, version: str,
        state_schema: str, entrypoint: str,
        required_capabilities: tuple[str, ...] = (),
    ) -> "DomainProgramBuilder":
        if kind not in _KIND_PREFIX:
            raise ValueError(f"unsupported programmable domain: {kind}")
        return cls(
            ResearchProgramBuilder(
                program_id=program_id, kind=kind, version=version,
                state_schema=state_schema, entrypoint=entrypoint,
                required_capabilities=required_capabilities,
            ),
            kind,
        )

    def operation(
        self, node_id: str, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "DomainProgramBuilder":
        prefix = _KIND_PREFIX[self.kind] + "."
        if not operation.startswith(prefix):
            raise ValueError(
                f"{self.kind.value} operation must use native prefix {prefix!r}; "
                "use custom() for paper-private namespaces"
            )
        return self.custom(
            node_id, operation, configuration=configuration, next_node=next_node,
            required_capabilities=required_capabilities,
        )

    def custom(
        self, node_id: str, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "DomainProgramBuilder":
        self._builder.node(
            node_id, operation, configuration=configuration, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self

    def build(self) -> ResearchProgram:
        return self._builder.build()


class RuntimeProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "RuntimeProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.RUNTIME, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.RUNTIME)

    def semantic(
        self, node_id: str, concern: RuntimeConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "RuntimeProgramBuilder":
        if not isinstance(concern, RuntimeConcern):
            raise TypeError("runtime concern must be RuntimeConcern")
        config = {} if configuration is None else dict(configuration)
        config["runtime_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self


def _domain_builder(name: str, kind: MachineKind):
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ):
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=kind, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, kind)
    return type(name, (DomainProgramBuilder,), {"create": classmethod(create)})


class ParticipantProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "ParticipantProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.PARTICIPANT, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.PARTICIPANT)

    def semantic(
        self, node_id: str, concern: ParticipantConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "ParticipantProgramBuilder":
        if not isinstance(concern, ParticipantConcern):
            raise TypeError("participant concern must be ParticipantConcern")
        config = {} if configuration is None else dict(configuration)
        config["participant_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self


class EnvironmentProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "EnvironmentProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.ENVIRONMENT, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.ENVIRONMENT)

    def semantic(
        self, node_id: str, concern: EnvironmentConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "EnvironmentProgramBuilder":
        if not isinstance(concern, EnvironmentConcern):
            raise TypeError("environment concern must be EnvironmentConcern")
        config = {} if configuration is None else dict(configuration)
        config["environment_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self


class MemoryProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "MemoryProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.MEMORY, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.MEMORY)

    def semantic(
        self, node_id: str, concern: MemoryConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "MemoryProgramBuilder":
        if not isinstance(concern, MemoryConcern):
            raise TypeError("memory concern must be MemoryConcern")
        config = {} if configuration is None else dict(configuration)
        config["memory_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self
class EvaluationProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "EvaluationProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.EVALUATION, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.EVALUATION)

    def semantic(
        self, node_id: str, concern: EvaluationConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "EvaluationProgramBuilder":
        if not isinstance(concern, EvaluationConcern):
            raise TypeError("evaluation concern must be EvaluationConcern")
        config = {} if configuration is None else dict(configuration)
        config["evaluation_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self


class OptimizationProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "OptimizationProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.OPTIMIZATION, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.OPTIMIZATION)

    def semantic(
        self, node_id: str, concern: OptimizationConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "OptimizationProgramBuilder":
        if not isinstance(concern, OptimizationConcern):
            raise TypeError("optimization concern must be OptimizationConcern")
        config = {} if configuration is None else dict(configuration)
        config["optimization_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self


class ExperimentProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "ExperimentProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.EXPERIMENT, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.EXPERIMENT)

    def semantic(
        self, node_id: str, concern: ExperimentConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "ExperimentProgramBuilder":
        if not isinstance(concern, ExperimentConcern):
            raise TypeError("experiment concern must be ExperimentConcern")
        config = {} if configuration is None else dict(configuration)
        config["experiment_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self


class ResearchRunProgramBuilder(DomainProgramBuilder):
    @classmethod
    def create(
        cls, *, program_id: str, version: str, state_schema: str,
        entrypoint: str, required_capabilities: tuple[str, ...] = (),
    ) -> "ResearchRunProgramBuilder":
        base = DomainProgramBuilder.create(
            program_id=program_id, kind=MachineKind.RUN, version=version,
            state_schema=state_schema, entrypoint=entrypoint,
            required_capabilities=required_capabilities,
        )
        return cls(base._builder, MachineKind.RUN)

    def semantic(
        self, node_id: str, concern: RunConcern, operation: str, *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "ResearchRunProgramBuilder":
        if not isinstance(concern, RunConcern):
            raise TypeError("run concern must be RunConcern")
        config = {} if configuration is None else dict(configuration)
        config["run_concern"] = concern.value
        self.custom(
            node_id, operation, configuration=config, next_node=next_node,
            required_capabilities=required_capabilities,
        )
        return self


__all__ = [
    "DomainProgramBuilder",
    "EnvironmentConcern",
    "EnvironmentProgramBuilder",
    "EvaluationConcern",
    "EvaluationProgramBuilder",
    "ExperimentConcern",
    "ExperimentProgramBuilder",
    "MemoryConcern",
    "MemoryProgramBuilder",
    "OptimizationConcern",
    "OptimizationProgramBuilder",
    "ParticipantConcern",
    "ParticipantProgramBuilder",
    "ResearchRunProgramBuilder",
    "RunConcern",
    "RuntimeConcern",
    "RuntimeProgramBuilder",
]
