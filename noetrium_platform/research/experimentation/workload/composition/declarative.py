from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.unit_driver import UnitActivationRuntimePort

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from noetrium_platform.research.execution.api import CapabilityPort
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)
from noetrium_platform.research.execution.api import (
    MethodAgentLoopPort,
    MethodObservationPort,
    NoetriumUnit,
    MethodRunResult,
    MethodRunStatus,
    MethodRuntimeContext,
    MethodRuntimePort,
    MethodSchemaPort,
    analyze_method_runtime_requirements,
)
from noetrium_platform.research.execution.api import OperationDispatchPort
from noetrium_platform.research.execution.api import (
    method_program_digest,
    method_program_state_schema,
    method_program_input_schema,
    method_program_output_schema,
)
from noetrium_platform.research.execution.api import (
    ExecutionBudgetAuthorityPort,
)
from noetrium_platform.research.execution.api import (
    MethodEvidenceFactoryPort,
    MethodRuntimePortInventory,
    plan_method_runtime_binding,
    require_complete_method_runtime_binding,
)

from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_task_unit,
    task_field,
    task_id,
    task_lineage_id,
)

from ..api import WorkloadEvaluation, WorkloadMethodInvocation


def _safe_task_key(task: NoetriumUnit) -> str:
    return f"task-{canonical_digest({'task_id': task_id(task), 'lineage_id': task_lineage_id(task)})[:24]}"


def _lifetime_invocation_key(context: ExecutionContext) -> str | None:
    if context.lifetime_id is None:
        return None
    return canonical_digest({"lifetime_id": context.lifetime_id})[:24]


def _port_identity(value: object, name: str) -> str:
    digest = getattr(value, "identity_digest", None)
    return require_sha256(digest, f"declarative workload {name} identity_digest")


@dataclass(frozen=True, slots=True)
class TaskFieldProjection:
    """Data-only projection from NoetriumUnit into a JSON object."""

    fields: tuple[tuple[str, str], ...] = (
        ("task_id", "task_id"),
        ("family", "family"),
        ("objective", "objective"),
        ("context", "context"),
        ("lineage_id", "lineage_id"),
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

    @staticmethod
    def _resolve(task: NoetriumUnit, source_path: str) -> JsonValue:
        root_name, *parts = source_path.split(".")
        try:
            value: object = task_field(task, root_name)
        except KeyError as exc:
            raise ValueError(f"task Unit has no semantic field {root_name!r}") from exc
        for part in parts:
            if not isinstance(value, Mapping) or part not in value:
                raise KeyError(
                    f"task projection source path is missing: {source_path}"
                )
            value = value[part]
        return freeze_json(value)

    def project(self, task: NoetriumUnit) -> JsonObject:
        require_task_unit(task)
        value: dict[str, JsonValue] = dict(self.constants)
        for output_name, source_name in self.fields:
            value[output_name] = self._resolve(task, source_name)
        frozen = freeze_json(value)
        if not isinstance(frozen, Mapping):
            raise TypeError("task projection must freeze to a JSON object")
        return frozen


@dataclass(frozen=True, slots=True)
class MethodResultProjection:
    """Project an explicit JSON subset out of one MethodRunResult."""

    fields: tuple[tuple[str, str], ...] = ()
    constants: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.fields) is not tuple:
            raise TypeError("method result projection fields must be a tuple")
        names: list[str] = []
        for item in self.fields:
            if (
                type(item) is not tuple
                or len(item) != 2
                or any(type(value) is not str or not value.strip() for value in item)
            ):
                raise TypeError(
                    "method result projection fields must be "
                    "(output, path) text pairs"
                )
            if item[1].split(".", 1)[0] not in {
                "value",
                "state",
                "diagnostics",
            }:
                raise ValueError(
                    "method result projection path must start with "
                    "value, state or diagnostics"
                )
            names.append(item[0])
        if len(names) != len(set(names)):
            raise ValueError(
                "method result projection output fields must be unique"
            )
        if not isinstance(self.constants, Mapping):
            raise TypeError(
                "method result projection constants must be a mapping"
            )
        overlap = set(names) & set(self.constants)
        if overlap:
            raise ValueError(
                "method result projection constants overlap projected fields: "
                f"{sorted(overlap)}"
            )
        object.__setattr__(self, "constants", freeze_json(self.constants))

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "projection": "method-result-fields.v1",
                "fields": self.fields,
                "constants": self.constants,
            }
        )

    @staticmethod
    def _resolve(result: MethodRunResult, path: str) -> JsonValue:
        root_name, *parts = path.split(".")
        value: object = getattr(result, root_name)
        for part in parts:
            if not isinstance(value, Mapping) or part not in value:
                raise KeyError(
                    f"method result projection path is missing: {path}"
                )
            value = value[part]
        frozen = freeze_json(value)
        return frozen

    def project(self, result: MethodRunResult) -> JsonObject:
        if not isinstance(result, MethodRunResult):
            raise TypeError(
                "method result projection requires MethodRunResult"
            )
        value: dict[str, JsonValue] = dict(self.constants)
        for output_name, path in self.fields:
            value[output_name] = self._resolve(result, path)
        frozen = freeze_json(value)
        if not isinstance(frozen, Mapping):
            raise TypeError(
                "method result projection must freeze to a JSON object"
            )
        return frozen


def observed_method_event_costs(events: Sequence[object]) -> dict[str, int]:
    """Reduce already accepted Method events into evaluator-only costs."""
    if isinstance(events, (str, bytes, bytearray)) or not isinstance(events, Sequence):
        raise TypeError("execution event cost projection requires a sequence")
    model_tokens = 0
    physical_child_effects = 0
    for event in events:
        if not hasattr(event, "kind") or not hasattr(event, "payload"):
            raise TypeError("execution event cost projection requires Method events")
        payload = event.payload
        if not isinstance(payload, Mapping):
            continue
        if event.kind == "model.invocation":
            for key in ("input_tokens", "output_tokens"):
                value = payload.get(key)
                if type(value) is int and value >= 0:
                    model_tokens += value
            continue
        if event.kind != "capability.evidence":
            continue
        evidence = payload.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        diagnostics = evidence.get("environment_diagnostics")
        if not isinstance(diagnostics, Mapping):
            continue
        value = diagnostics.get("physical_child_effect_count")
        if type(value) is int and value >= 0:
            physical_child_effects += value
    return {
        "model_tokens": model_tokens,
        "physical_child_effects": physical_child_effects,
    }


def observed_method_execution_costs(result: MethodRunResult) -> dict[str, int]:
    """Reduce sealed Method evidence into evaluator-only execution costs.

    This is the single common-substrate cost projection for both direct and
    scheduled-participant workloads. Values are derived only from provider
    invocation usage and physical Environment evidence and must never enter
    Method/Agent-visible participant context.
    """
    if not isinstance(result, MethodRunResult):
        raise TypeError("execution cost projection requires MethodRunResult")
    model_tokens = 0
    physical_child_effects = 0
    for event in result.events:
        payload = event.payload
        if not isinstance(payload, Mapping):
            continue
        if event.kind == "model.invocation":
            for key in ("input_tokens", "output_tokens"):
                value = payload.get(key)
                if type(value) is int and value >= 0:
                    model_tokens += value
            continue
        if event.kind != "capability.evidence":
            continue
        evidence = payload.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        diagnostics = evidence.get("environment_diagnostics")
        if not isinstance(diagnostics, Mapping):
            continue
        value = diagnostics.get("physical_child_effect_count")
        if type(value) is int and value >= 0:
            physical_child_effects += value
    return {
        "model_tokens": model_tokens,
        "physical_child_effects": physical_child_effects,
    }


@dataclass(frozen=True, slots=True)
class DeclarativeExecutionResultAdapter:
    """Map Method execution status plus an explicit export projection.

    This adapter does not decide benchmark correctness. It is appropriate for
    execution-stage providers and for workloads whose success is exactly Method
    completion. Benchmark correctness with an external verifier remains owned by
    that verifier.
    """

    export_projection: MethodResultProjection = field(
        default_factory=MethodResultProjection
    )
    success_utility: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.export_projection, MethodResultProjection):
            raise TypeError(
                "declarative result adapter requires MethodResultProjection"
            )
        if isinstance(self.success_utility, bool) or not isinstance(
            self.success_utility, (int, float)
        ):
            raise TypeError(
                "declarative result adapter success_utility must be numeric"
            )

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "adapter": "declarative-execution-result.v1",
                "export_projection_digest": self.export_projection.digest,
                "success_utility": float(self.success_utility),
            }
        )

    def evaluate(
        self,
        task: NoetriumUnit,
        result: MethodRunResult,
    ) -> WorkloadEvaluation:
        require_task_unit(task)
        if not isinstance(result, MethodRunResult):
            raise TypeError(
                "declarative result adapter requires MethodRunResult"
            )
        succeeded = result.status is MethodRunStatus.SUCCEEDED
        observed_costs = observed_method_execution_costs(result)
        return WorkloadEvaluation(
            success=succeeded,
            utility=float(self.success_utility) if succeeded else 0.0,
            failure_reason=(
                ""
                if succeeded
                else (
                    result.failure
                    or result.failure_code
                    or result.status.value
                )
            ),
            diagnostics={
                "method_run_digest": result.run_digest,
                "method_status": result.status.value,
                "failure_id": result.failure_id,
                "model_call_count": sum(
                    1 for event in result.events if event.kind == "model.invocation"
                ),
                **observed_costs,
            },
            exports=(
                self.export_projection.project(result)
                if succeeded
                else {}
            ),
        )


@dataclass(frozen=True, slots=True)
class MethodRuntimeBindings:
    """Reusable non-execution dependencies for declarative Method invocations.

    The task/run ExecutionContext is deliberately excluded. A compiler creates a
    fresh context, evidence sink and Machine authority per task.
    """

    bind_runtime: Callable[..., MethodRuntimeContext]
    runtime_binder_digest: str
    state_root: Path
    evidence_factory: MethodEvidenceFactoryPort | None = None
    capabilities: CapabilityPort | None = None
    dispatcher: OperationDispatchPort | None = None
    observation: MethodObservationPort | None = None
    agent_loop: MethodAgentLoopPort | None = None
    schemas: MethodSchemaPort | None = None
    unit_activation: UnitActivationRuntimePort | None = None
    execution_budget: ExecutionBudgetAuthorityPort | None = None
    runtime_binding_digest: str | None = None
    _resolved_runtime_binding_digest: str = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not callable(self.bind_runtime):
            raise TypeError("declarative runtime bind_runtime must be callable")
        require_sha256(
            self.runtime_binder_digest,
            "declarative runtime binder identity",
        )
        if self.evidence_factory is not None and not isinstance(
            self.evidence_factory, MethodEvidenceFactoryPort
        ):
            raise TypeError("declarative runtime evidence_factory must satisfy MethodEvidenceFactoryPort")
        object.__setattr__(self, "state_root", Path(self.state_root))
        if self.execution_budget is not None and not isinstance(
            self.execution_budget,
            ExecutionBudgetAuthorityPort,
        ):
            raise TypeError(
                "declarative workload execution_budget must satisfy "
                "ExecutionBudgetAuthorityPort"
            )
        if self.runtime_binding_digest is not None:
            resolved = require_sha256(
                self.runtime_binding_digest,
                "declarative workload runtime_binding_digest",
            )
        else:
            identities: dict[str, str] = {
                "runtime_binder": self.runtime_binder_digest,
            }
            if self.evidence_factory is not None:
                identities["evidence_factory"] = _port_identity(
                    self.evidence_factory,
                    "evidence_factory",
                )
            for name, value in (
                ("capabilities", self.capabilities),
                ("dispatcher", self.dispatcher),
                ("observation", self.observation),
                ("agent_loop", self.agent_loop),
                ("schemas", self.schemas),
                ("unit_activation", self.unit_activation),
                ("execution_budget", self.execution_budget),
            ):
                if value is not None:
                    identities[name] = _port_identity(value, name)
            resolved = canonical_digest({
                "bindings": "declarative-method-runtime.v1",
                "ports": identities,
            })
        object.__setattr__(
            self,
            "_resolved_runtime_binding_digest",
            resolved,
        )

    def resolved_runtime_binding_digest(self) -> str:
        return self._resolved_runtime_binding_digest

    def materialize_context(
        self,
        *,
        program: NoetriumUnit,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
        binding_plan_digest: str,
        invocation_id: str | None = None,
    ) -> tuple[MethodRuntimeContext, Path]:
        if not isinstance(program, NoetriumUnit):
            raise TypeError("declarative runtime requires NoetriumUnit")
        require_task_unit(task)
        if not isinstance(context, ExecutionContext):
            raise TypeError("declarative runtime requires ExecutionContext")
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("declarative runtime requires ExecutionControlPort")
        require_sha256(binding_plan_digest, "declarative workload binding_plan_digest")
        if invocation_id is not None and (
            type(invocation_id) is not str or not invocation_id.strip()
        ):
            raise ValueError("declarative runtime invocation_id must be non-empty text")
        lifetime_key = _lifetime_invocation_key(context)
        invocation_key = (
            None
            if invocation_id is None
            else canonical_digest({"invocation_id": invocation_id})[:24]
        )
        base_run_id = (
            f"{context.run_id}:{task_id(task)}"
            if lifetime_key is None
            else f"{context.run_id}:lifetime:{lifetime_key}:{task_id(task)}"
        )
        execution = replace(
            context,
            run_id=(
                base_run_id
                if invocation_key is None
                else f"{base_run_id}:invocation:{invocation_key}"
            ),
            task_id=task_id(task),
            span_id=(
                f"{context.span_id}:{canonical_digest(task_id(task))[:12]}"
                if invocation_key is None
                else (
                    f"{context.span_id}:{canonical_digest(task_id(task))[:12]}"
                    f":invocation:{invocation_key[:12]}"
                )
            ),
        )
        runtime_binding_digest = self.resolved_runtime_binding_digest()
        schema_digest = canonical_digest({
            "state": method_program_state_schema(program),
            "input": method_program_input_schema(program),
            "output": method_program_output_schema(program),
        })
        if self.evidence_factory is None:
            raise RuntimeError(
                "durable declarative runtime requires MethodEvidenceFactoryPort"
            )
        task_root = self.state_root
        if lifetime_key is not None:
            task_root = task_root / f"lifetime-{lifetime_key}"
        task_root = task_root / _safe_task_key(task)
        if invocation_key is not None:
            task_root = task_root / f"invocation-{invocation_key}"
        evidence = self.evidence_factory.create(task_root / "evidence")
        runtime = MethodRuntimeContext(
            execution=execution,
            execution_control=control,
            capabilities=self.capabilities,
            dispatcher=self.dispatcher,
            evidence=evidence,
            observation=self.observation,
            agent_loop=self.agent_loop,
            schemas=self.schemas,
            unit_activation=self.unit_activation,
            execution_budget=self.execution_budget,
            binding_plan_digest=binding_plan_digest,
            runtime_binding_digest=runtime_binding_digest,
            schema_digest=schema_digest,
        )
        return runtime, task_root

    def bind(
        self,
        *,
        program: NoetriumUnit,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
        binding_plan_digest: str,
        invocation_id: str | None = None,
    ) -> MethodRuntimeContext:
        runtime, task_root = self.materialize_context(
            program=program,
            task=task,
            context=context,
            control=control,
            binding_plan_digest=binding_plan_digest,
            invocation_id=invocation_id,
        )
        return self.bind_runtime(
            program,
            runtime,
            state_root=task_root / "machine",
            machine_id=f"method:{runtime.execution.run_id}",
        )



def compose_method_runtime_bindings(
    program: NoetriumUnit,
    inventory: MethodRuntimePortInventory,
    *,
    bind_runtime: Callable[..., MethodRuntimeContext],
    runtime_binder_digest: str,
    evidence_factory: MethodEvidenceFactoryPort | None = None,
    state_root: str | Path,
    dispatcher: OperationDispatchPort,
    observation: MethodObservationPort | None = None,
    execution_budget: ExecutionBudgetAuthorityPort | None = None,
) -> MethodRuntimeBindings:
    """Resolve a NoetriumUnit runtime closure from one explicit shared inventory.

    Only ports required by the program are attached. Missing identities or
    capability/agent closure mismatches fail before any task is executed.
    """

    if not isinstance(program, NoetriumUnit):
        raise TypeError("runtime auto-composition requires NoetriumUnit")
    if not isinstance(inventory, MethodRuntimePortInventory):
        raise TypeError("runtime auto-composition requires MethodRuntimePortInventory")
    plan = plan_method_runtime_binding(program, inventory)
    require_complete_method_runtime_binding(plan)
    requirements = analyze_method_runtime_requirements(program)
    ports = set(requirements.ports)
    return MethodRuntimeBindings(
        bind_runtime=bind_runtime,
        runtime_binder_digest=runtime_binder_digest,
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
        unit_activation=(
            inventory.unit_activation
            if MethodRuntimePort.UNIT_ACTIVATION in ports
            else None
        ),
        state_root=Path(state_root),
        execution_budget=execution_budget,
        runtime_binding_digest=plan.semantic_digest,
    )


@dataclass(frozen=True, slots=True)
class DeclarativeWorkloadMethodCompiler:
    """Compile standard tasks into Method invocations without paper runner classes."""

    program: NoetriumUnit
    runtime: MethodRuntimeBindings
    input_projection: TaskFieldProjection = field(default_factory=TaskFieldProjection)
    initial_state: JsonObject | None = None
    initial_state_projection: TaskFieldProjection | None = None
    resume: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.program, NoetriumUnit):
            raise TypeError("declarative workload compiler requires NoetriumUnit")
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
            "program_digest": method_program_digest(self.program),
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
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadMethodInvocation:
        runtime = self.runtime.bind(
            program=self.program,
            task=task,
            context=context,
            control=control,
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
    "DeclarativeExecutionResultAdapter",
    "DeclarativeWorkloadMethodCompiler",
    "MethodResultProjection",
    "observed_method_event_costs",
    "observed_method_execution_costs",
    "compose_method_runtime_bindings",
    "MethodRuntimeBindings",
    "TaskFieldProjection",
]
