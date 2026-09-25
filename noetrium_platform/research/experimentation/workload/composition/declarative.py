from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from noetrium_platform.research.execution.api import CapabilityPort
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)
from noetrium_platform.research.execution.api import (
    AsyncOperationDispatchPort,
    MethodAgentLoopPort,
    MethodChildMachinePort,
    MethodObservationPort,
    MethodProgram,
    MethodRuntimeContext,
    MethodRuntimePort,
    MethodSchemaPort,
    analyze_method_runtime_requirements,
)
from noetrium_platform.research.execution.api import OperationDispatchPort
from noetrium_platform.research.execution.api import (
    MethodEvidenceFactoryPort,
    MethodRuntimeBinderPort,
    MethodRuntimePortInventory,
    plan_method_runtime_binding,
)
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentTaskSpec

from ..api import WorkloadMethodInvocation


def _safe_task_key(task: ExperimentTaskSpec) -> str:
    return f"task-{canonical_digest({'task_id': task.task_id, 'lineage_id': task.lineage_id})[:24]}"


def _port_identity(value: object, name: str) -> str:
    digest = getattr(value, "identity_digest", None)
    return require_sha256(digest, f"declarative workload {name} identity_digest")


@dataclass(frozen=True, slots=True)
class TaskFieldProjection:
    """Data-only projection from ExperimentTaskSpec into a JSON object."""

    fields: tuple[tuple[str, str], ...] = (
        ("task_id", "task_id"),
        ("family", "family"),
        ("objective", "objective"),
        ("context", "context"),
        ("lineage_id", "lineage_id"),
        ("depends_on_task_ids", "depends_on_task_ids"),
        ("retry_of_task_id", "retry_of_task_id"),
        ("max_steps", "max_steps"),
        ("max_seconds", "max_seconds"),
    )
    constants: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.fields) is not tuple:
            raise TypeError("task projection fields must be a tuple")
        output_names: list[str] = []
        for item in self.fields:
            if (
                type(item) is not tuple
                or len(item) != 2
                or any(type(value) is not str or not value.strip() for value in item)
            ):
                raise TypeError("task projection fields must be (output, source) text pairs")
            output_names.append(item[0])
        if len(output_names) != len(set(output_names)):
            raise ValueError("task projection output fields must be unique")
        if not isinstance(self.constants, Mapping):
            raise TypeError("task projection constants must be a mapping")
        overlap = set(output_names) & set(self.constants)
        if overlap:
            raise ValueError(f"task projection constants overlap projected fields: {sorted(overlap)}")
        object.__setattr__(self, "constants", freeze_json(self.constants))

    @property
    def digest(self) -> str:
        return canonical_digest({
            "projection": "experiment-task-fields.v1",
            "fields": self.fields,
            "constants": self.constants,
        })

    def project(self, task: ExperimentTaskSpec) -> JsonObject:
        if not isinstance(task, ExperimentTaskSpec):
            raise TypeError("task projection requires ExperimentTaskSpec")
        value: dict[str, JsonValue] = dict(self.constants)
        for output_name, source_name in self.fields:
            if not hasattr(task, source_name):
                raise ValueError(f"ExperimentTaskSpec has no field {source_name!r}")
            value[output_name] = getattr(task, source_name)
        frozen = freeze_json(value)
        if not isinstance(frozen, Mapping):
            raise TypeError("task projection must freeze to a JSON object")
        return frozen


@dataclass(frozen=True, slots=True)
class MethodRuntimeBindings:
    """Reusable non-execution dependencies for declarative Method invocations.

    The task/run ExecutionContext is deliberately excluded. A compiler creates a
    fresh context, evidence sink and Machine authority per task.
    """

    runtime_binder: MethodRuntimeBinderPort
    evidence_factory: MethodEvidenceFactoryPort | None = None
    capabilities: CapabilityPort | None = None
    dispatcher: OperationDispatchPort | None = None
    observation: MethodObservationPort | None = None
    agent_loop: MethodAgentLoopPort | None = None
    schemas: MethodSchemaPort | None = None
    child_machines: MethodChildMachinePort | None = None
    async_dispatcher: AsyncOperationDispatchPort | None = None
    state_root: Path | None = None
    runtime_binding_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_binder, MethodRuntimeBinderPort):
            raise TypeError("declarative runtime requires MethodRuntimeBinderPort")
        if self.evidence_factory is not None and not isinstance(
            self.evidence_factory, MethodEvidenceFactoryPort
        ):
            raise TypeError("declarative runtime evidence_factory must satisfy MethodEvidenceFactoryPort")
        if self.state_root is not None:
            object.__setattr__(self, "state_root", Path(self.state_root))
        if self.runtime_binding_digest is not None:
            require_sha256(self.runtime_binding_digest, "declarative workload runtime_binding_digest")

    def resolved_runtime_binding_digest(self) -> str:
        if self.runtime_binding_digest is not None:
            return self.runtime_binding_digest
        identities: dict[str, str] = {
            "runtime_binder": _port_identity(self.runtime_binder, "runtime_binder"),
        }
        if self.evidence_factory is not None:
            identities["evidence_factory"] = _port_identity(
                self.evidence_factory, "evidence_factory"
            )
        for name, value in (
            ("capabilities", self.capabilities),
            ("dispatcher", self.dispatcher),
            ("observation", self.observation),
            ("agent_loop", self.agent_loop),
            ("schemas", self.schemas),
            ("child_machines", self.child_machines),
            ("async_dispatcher", self.async_dispatcher),
        ):
            if value is not None:
                identities[name] = _port_identity(value, name)
        return canonical_digest({
            "bindings": "declarative-method-runtime.v1",
            "ports": identities,
        })

    def bind(
        self,
        *,
        program: MethodProgram,
        task: ExperimentTaskSpec,
        context: ExecutionContext,
        binding_plan_digest: str,
    ) -> MethodRuntimeContext:
        if not isinstance(program, MethodProgram):
            raise TypeError("declarative runtime requires MethodProgram")
        if not isinstance(task, ExperimentTaskSpec):
            raise TypeError("declarative runtime requires ExperimentTaskSpec")
        if not isinstance(context, ExecutionContext):
            raise TypeError("declarative runtime requires ExecutionContext")
        require_sha256(binding_plan_digest, "declarative workload binding_plan_digest")
        execution = replace(
            context,
            run_id=f"{context.run_id}:{task.task_id}",
            task_id=task.task_id,
            span_id=f"{context.span_id}:{canonical_digest(task.task_id)[:12]}",
        )
        runtime_binding_digest = self.resolved_runtime_binding_digest()
        schema_digest = canonical_digest({
            "state": program.state_schema,
            "input": program.input_schema,
            "output": program.output_schema,
        })
        task_root: Path | None = None
        evidence = None
        if self.state_root is not None:
            if self.evidence_factory is None:
                raise RuntimeError(
                    "durable declarative runtime requires MethodEvidenceFactoryPort"
                )
            task_root = self.state_root / _safe_task_key(task)
            evidence = self.evidence_factory.create(task_root / "evidence")
        runtime = MethodRuntimeContext(
            execution=execution,
            capabilities=self.capabilities,
            dispatcher=self.dispatcher,
            evidence=evidence,
            observation=self.observation,
            agent_loop=self.agent_loop,
            schemas=self.schemas,
            child_machines=self.child_machines,
            async_dispatcher=self.async_dispatcher,
            binding_plan_digest=binding_plan_digest,
            runtime_binding_digest=runtime_binding_digest,
            schema_digest=schema_digest,
        )
        return self.runtime_binder.bind(
            program,
            runtime,
            state_root=None if task_root is None else task_root / "machine",
            machine_id=f"method:{execution.run_id}",
        )


def compose_method_runtime_bindings(
    program: MethodProgram,
    inventory: MethodRuntimePortInventory,
    *,
    runtime_binder: MethodRuntimeBinderPort,
    evidence_factory: MethodEvidenceFactoryPort | None = None,
    state_root: str | Path | None = None,
    dispatcher: OperationDispatchPort | None = None,
    observation: MethodObservationPort | None = None,
    async_dispatcher: AsyncOperationDispatchPort | None = None,
) -> MethodRuntimeBindings:
    """Resolve a MethodProgram runtime closure from one explicit shared inventory.

    Only ports required by the program are attached. Missing identities or
    capability/agent closure mismatches fail before any task is executed.
    """

    if not isinstance(program, MethodProgram):
        raise TypeError("runtime auto-composition requires MethodProgram")
    if not isinstance(inventory, MethodRuntimePortInventory):
        raise TypeError("runtime auto-composition requires MethodRuntimePortInventory")
    plan = plan_method_runtime_binding(program, inventory)
    plan.require_complete()
    requirements = analyze_method_runtime_requirements(program)
    ports = set(requirements.ports)
    return MethodRuntimeBindings(
        runtime_binder=runtime_binder,
        evidence_factory=evidence_factory,
        capabilities=(
            inventory.capabilities
            if MethodRuntimePort.CAPABILITIES in ports
            else None
        ),
        dispatcher=dispatcher,
        observation=observation,
        agent_loop=(
            inventory.agent_loop
            if MethodRuntimePort.AGENT_LOOP in ports
            else None
        ),
        schemas=(
            inventory.schemas
            if MethodRuntimePort.SCHEMAS in ports
            else None
        ),
        child_machines=(
            inventory.child_machines
            if MethodRuntimePort.CHILD_MACHINES in ports
            else None
        ),
        async_dispatcher=async_dispatcher,
        state_root=None if state_root is None else Path(state_root),
        runtime_binding_digest=plan.digest,
    )


@dataclass(frozen=True, slots=True)
class DeclarativeWorkloadMethodCompiler:
    """Compile standard tasks into Method invocations without paper runner classes."""

    program: MethodProgram
    runtime: MethodRuntimeBindings
    input_projection: TaskFieldProjection = field(default_factory=TaskFieldProjection)
    initial_state: JsonObject | None = None
    initial_state_projection: TaskFieldProjection | None = None
    resume: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.program, MethodProgram):
            raise TypeError("declarative workload compiler requires MethodProgram")
        if not isinstance(self.runtime, MethodRuntimeBindings):
            raise TypeError("declarative workload compiler requires MethodRuntimeBindings")
        if not isinstance(self.input_projection, TaskFieldProjection):
            raise TypeError("declarative workload compiler requires TaskFieldProjection")
        if self.initial_state is not None:
            if not isinstance(self.initial_state, Mapping):
                raise TypeError("declarative workload initial_state must be a mapping or None")
            object.__setattr__(self, "initial_state", freeze_json(self.initial_state))
        if self.initial_state_projection is not None:
            if not isinstance(self.initial_state_projection, TaskFieldProjection):
                raise TypeError(
                    "declarative workload initial_state_projection must be "
                    "TaskFieldProjection or None"
                )
            if self.initial_state is not None:
                raise ValueError(
                    "declarative workload accepts static initial_state or "
                    "initial_state_projection, not both"
                )
        if type(self.resume) is not bool:
            raise TypeError("declarative workload resume must be boolean")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "compiler": "declarative-workload-method.v1",
            "program_digest": self.program.program_digest,
            "runtime_binding_digest": self.runtime.resolved_runtime_binding_digest(),
            "input_projection_digest": self.input_projection.digest,
            "initial_state": self.initial_state,
            "initial_state_projection_digest": (
                None
                if self.initial_state_projection is None
                else self.initial_state_projection.digest
            ),
            "resume": self.resume,
        })

    def compile(
        self,
        task: ExperimentTaskSpec,
        context: ExecutionContext,
    ) -> WorkloadMethodInvocation:
        runtime = self.runtime.bind(
            program=self.program,
            task=task,
            context=context,
            binding_plan_digest=self.digest,
        )
        analyze_method_runtime_requirements(self.program).require(runtime)
        initial_state = (
            self.initial_state
            if self.initial_state_projection is None
            else self.initial_state_projection.project(task)
        )
        return WorkloadMethodInvocation(
            program=self.program,
            runtime=runtime,
            input_value=self.input_projection.project(task),
            initial_state=initial_state,
            resume=self.resume,
        )


__all__ = [
    "DeclarativeWorkloadMethodCompiler",
    "compose_method_runtime_bindings",
    "MethodRuntimeBindings",
    "TaskFieldProjection",
]
