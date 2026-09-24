from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import importlib
import inspect
from typing import Callable, Protocol, runtime_checkable

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    MachineKind,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram as MachineResearchProgram,
    ResearchProgramBuilder as MachineResearchProgramBuilder,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)
from noetrium_platform.product.research_os import (
    ResearchDefinition,
    ResearchDefinitionKind,
    ResearchImplementation,
    ResearchMethodProgramImplementation,
    ResearchNodeKind,
)

from .research_os_experiment import (
    ResearchOSExperimentClosure,
    ResearchOSExperimentClosureMissing,
    ResearchOSExperimentClosurePort,
)
from .research_os_graph import (
    CompiledResearchOSGraphNode,
    CompiledResearchOSGraph,
)


class ResearchOSLoweringTarget(StrEnum):
    """Existing authority family selected for one top-level research node.

    This is an internal compiler IR.  It does not create a second execution
    authority: every target names an already-existing lower semantic owner.
    """

    METHOD_MACHINE = "method-machine"
    EXPERIMENTATION = "experimentation"
    RUN_MACHINE = "run-machine"
    EVALUATION_MACHINE = "evaluation-machine"
    OPTIMIZATION_MACHINE = "optimization-machine"
    ANALYSIS_MACHINE = "analysis-machine"
    PUBLICATION_MACHINE = "publication-machine"
    CUSTOM_MACHINE = "custom-machine"


_NODE_TARGETS: dict[ResearchNodeKind, ResearchOSLoweringTarget] = {
    ResearchNodeKind.METHOD: ResearchOSLoweringTarget.METHOD_MACHINE,
    ResearchNodeKind.STUDY: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.EXPERIMENT: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.RUN: ResearchOSLoweringTarget.RUN_MACHINE,
    ResearchNodeKind.TRIAL: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.EVALUATION: ResearchOSLoweringTarget.EVALUATION_MACHINE,
    ResearchNodeKind.ANALYSIS: ResearchOSLoweringTarget.ANALYSIS_MACHINE,
    ResearchNodeKind.OPTIMIZATION: ResearchOSLoweringTarget.OPTIMIZATION_MACHINE,
    ResearchNodeKind.SELECTION: ResearchOSLoweringTarget.ANALYSIS_MACHINE,
    ResearchNodeKind.ABLATION: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.ROBUSTNESS: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.SCALING: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.FIGURE: ResearchOSLoweringTarget.ANALYSIS_MACHINE,
    ResearchNodeKind.TABLE: ResearchOSLoweringTarget.ANALYSIS_MACHINE,
    ResearchNodeKind.PUBLICATION: ResearchOSLoweringTarget.PUBLICATION_MACHINE,
    ResearchNodeKind.CUSTOM: ResearchOSLoweringTarget.CUSTOM_MACHINE,
}
if set(_NODE_TARGETS) != set(ResearchNodeKind):
    raise RuntimeError("Research OS lowering table must cover every ResearchNodeKind")


_NODE_MACHINE_KINDS: dict[ResearchNodeKind, MachineKind] = {
    ResearchNodeKind.RUN: MachineKind.RUN,
    ResearchNodeKind.EVALUATION: MachineKind.EVALUATION,
    ResearchNodeKind.OPTIMIZATION: MachineKind.OPTIMIZATION,
    ResearchNodeKind.ANALYSIS: MachineKind.ANALYSIS,
    ResearchNodeKind.SELECTION: MachineKind.ANALYSIS,
    ResearchNodeKind.FIGURE: MachineKind.ANALYSIS,
    ResearchNodeKind.TABLE: MachineKind.ANALYSIS,
    ResearchNodeKind.PUBLICATION: MachineKind.PUBLICATION,
    ResearchNodeKind.CUSTOM: MachineKind.RUNTIME,
}


class ResearchImplementationResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedResearchImplementation:
    definition_id: str
    declared: ResearchImplementation
    implementation: Callable[..., object]

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError("resolved research implementation definition_id is required")
        if type(self.declared) is not ResearchImplementation:
            raise TypeError("resolved research implementation requires ResearchImplementation")
        if not callable(self.implementation):
            raise TypeError("resolved research implementation value must be callable")


@dataclass(frozen=True, slots=True)
class ResolvedResearchMethodProgramImplementation:
    """Resolved immutable MethodProgram symbol owned by one METHOD definition."""

    definition_id: str
    declared: ResearchMethodProgramImplementation
    program: MethodProgram

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError(
                "resolved MethodProgram implementation definition_id is required"
            )
        if type(self.declared) is not ResearchMethodProgramImplementation:
            raise TypeError(
                "resolved MethodProgram implementation requires typed declaration"
            )
        if type(self.program) is not MethodProgram:
            raise TypeError(
                "resolved MethodProgram implementation requires exact MethodProgram"
            )
        if self.program.program_digest != self.declared.program_digest:
            raise ValueError(
                "resolved MethodProgram digest drifted from immutable declaration"
            )


@runtime_checkable
class ResearchImplementationResolverPort(Protocol):
    def resolve(
        self,
        definition: ResearchDefinition,
    ) -> ResolvedResearchImplementation: ...


class ImportResearchImplementationResolver:
    """Resolve frozen implementation coordinates and fail closed on code drift."""

    def resolve(
        self,
        definition: ResearchDefinition,
    ) -> ResolvedResearchImplementation:
        if type(definition) is not ResearchDefinition:
            raise TypeError("implementation resolution requires ResearchDefinition")
        declared = definition.implementation
        if declared is None:
            raise ResearchImplementationResolutionError(
                f"definition is platform-resolved and has no paper implementation: "
                f"{definition.definition_id}"
            )
        try:
            value: object = importlib.import_module(declared.module)
            for part in declared.qualname.split("."):
                value = getattr(value, part)
        except (ImportError, AttributeError) as exc:
            raise ResearchImplementationResolutionError(
                "research implementation can no longer be imported from its frozen "
                f"coordinates: {declared.module}:{declared.qualname}"
            ) from exc
        if not callable(value):
            raise ResearchImplementationResolutionError(
                "frozen research implementation coordinates no longer resolve to "
                f"a callable: {declared.module}:{declared.qualname}"
            )
        try:
            observed = ResearchImplementation.from_callable(
                declared.implementation_id,
                value,
            )
        except (TypeError, ValueError, OSError) as exc:
            raise ResearchImplementationResolutionError(
                "could not reconstruct research implementation source identity: "
                f"{declared.module}:{declared.qualname}"
            ) from exc
        if observed != declared:
            raise ResearchImplementationResolutionError(
                "research implementation source drifted from the immutable revision: "
                f"{declared.module}:{declared.qualname}; "
                f"declared={declared.implementation_digest} "
                f"observed={observed.implementation_digest}"
            )
        return ResolvedResearchImplementation(
            definition.definition_id,
            declared,
            value,
        )


def resolve_method_program_implementation(
    definition: ResearchDefinition,
) -> ResolvedResearchMethodProgramImplementation:
    """Resolve one frozen module-level MethodProgram and prove exact IR identity."""

    if type(definition) is not ResearchDefinition:
        raise TypeError("MethodProgram resolution requires ResearchDefinition")
    if definition.kind is not ResearchDefinitionKind.METHOD:
        raise ValueError("MethodProgram resolution requires METHOD definition")
    declared = definition.implementation
    if type(declared) is not ResearchMethodProgramImplementation:
        raise TypeError(
            "MethodProgram resolution requires ResearchMethodProgramImplementation"
        )
    try:
        value: object = importlib.import_module(declared.module)
        for part in declared.qualname.split("."):
            value = getattr(value, part)
    except (ImportError, AttributeError) as exc:
        raise ResearchImplementationResolutionError(
            "research MethodProgram can no longer be imported from frozen "
            f"coordinates: {declared.module}:{declared.qualname}"
        ) from exc
    if type(value) is not MethodProgram:
        raise ResearchImplementationResolutionError(
            "frozen research MethodProgram coordinates no longer resolve to "
            f"MethodProgram: {declared.module}:{declared.qualname}"
        )
    if value.program_digest != declared.program_digest:
        raise ResearchImplementationResolutionError(
            "research MethodProgram IR drifted from immutable revision: "
            f"{declared.module}:{declared.qualname}; "
            f"declared={declared.program_digest} observed={value.program_digest}"
        )
    return ResolvedResearchMethodProgramImplementation(
        definition.definition_id,
        declared,
        value,
    )


def _plain_callable_accepts_payload(
    implementation: Callable[..., object],
) -> bool:
    """Determine invocation shape without executing author code."""

    try:
        signature = inspect.signature(implementation)
    except (TypeError, ValueError) as exc:
        raise ResearchImplementationResolutionError(
            "research implementation signature cannot be inspected"
        ) from exc
    marker = object()
    try:
        signature.bind(marker)
    except TypeError:
        try:
            signature.bind()
        except TypeError as exc:
            raise ResearchImplementationResolutionError(
                "plain research implementation must accept either zero or one "
                "positional payload argument"
            ) from exc
        return False
    return True


def _invoke_plain_callable(
    implementation: Callable[..., object],
    *,
    accepts_payload: bool,
    payload: JsonValue,
) -> object:
    return implementation(payload) if accepts_payload else implementation()



def compile_callable_method_definition(
    definition: ResearchDefinition,
    *,
    resolved: ResolvedResearchImplementation | None = None,
    resolver: ResearchImplementationResolverPort | None = None,
) -> MethodProgram:
    """Compile one ordinary paper METHOD callable into the canonical UMM IR.

    The author callable is treated as one pure semantic compute boundary: the
    wrapper itself performs no provider I/O. External effects still have to flow
    through MethodProgram capabilities/runtime ports, so this helper cannot
    silently become a second execution authority.
    """

    if type(definition) is not ResearchDefinition:
        raise TypeError("callable method lowering requires ResearchDefinition")
    if definition.kind is not ResearchDefinitionKind.METHOD:
        raise ValueError("callable method lowering requires METHOD definition")
    if definition.implementation is None:
        raise ResearchImplementationResolutionError(
            "METHOD definition has no paper implementation"
        )
    if resolved is not None and resolver is not None:
        raise ValueError("method lowering accepts resolved or resolver, not both")
    selected = (
        resolved
        if resolved is not None
        else (
            resolver
            if resolver is not None
            else ImportResearchImplementationResolver()
        ).resolve(definition)
    )
    if (
        selected.definition_id != definition.definition_id
        or selected.declared != definition.implementation
    ):
        raise ResearchImplementationResolutionError(
            "resolved METHOD implementation does not match frozen definition"
        )
    declared = selected.declared
    implementation = selected.implementation
    accepts_payload = _plain_callable_accepts_payload(implementation)

    def invoke(request: MethodNodeRequest) -> MethodNodeResult:
        value = _invoke_plain_callable(
            implementation,
            accepts_payload=accepts_payload,
            payload=request.input_value,
        )
        if type(value) is MethodNodeResult:
            return value
        return MethodNodeResult(value=value)

    config_value = definition.config
    configuration = (
        dict(config_value)
        if isinstance(config_value, Mapping)
        else {"research_definition_config": config_value}
    )
    configuration["research_definition_id"] = definition.definition_id
    configuration["research_implementation_digest"] = (
        declared.implementation_digest
    )
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id=definition.definition_id,
            implementation_version=declared.source_digest,
            abi_version="research-os.callable-method.v1",
            schema_version="json",
            artifact_digest=declared.implementation_digest,
        ),
        configuration_digest=canonical_digest(definition.config),
    )
    builder = MethodProgramBuilder(identity, entrypoint="invoke")
    builder.return_node(
        "invoke",
        f"research-os.method:{definition.definition_id}",
        invoke,
    )
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
    )


@dataclass(frozen=True, slots=True)
class LoweredResearchMachineProgram:
    """One paper callable lowered to the shared non-Method ResearchProgram ABI."""

    definition_id: str
    machine_kind: MachineKind
    program: MachineResearchProgram
    operation: ResearchHostOperation

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError("lowered machine definition_id is required")
        if not isinstance(self.machine_kind, MachineKind):
            raise TypeError("lowered machine kind must be MachineKind")
        if self.machine_kind is MachineKind.METHOD:
            raise ValueError("Method definitions must use MethodProgram/UMM")
        if type(self.program) is not MachineResearchProgram:
            raise TypeError("lowered machine program must be ResearchProgram")
        if self.program.kind is not self.machine_kind:
            raise ValueError("lowered machine program kind drifted")
        if type(self.operation) is not ResearchHostOperation:
            raise TypeError("lowered machine operation must be ResearchHostOperation")


def compile_callable_machine_definition(
    definition: ResearchDefinition,
    *,
    machine_kind: MachineKind,
    resolved: ResolvedResearchImplementation | None = None,
    resolver: ResearchImplementationResolverPort | None = None,
) -> LoweredResearchMachineProgram:
    """Compile one non-Method paper callable to ResearchProgram + host operation."""

    if type(definition) is not ResearchDefinition:
        raise TypeError("callable machine lowering requires ResearchDefinition")
    if definition.kind is ResearchDefinitionKind.METHOD:
        raise ValueError("METHOD definition must lower through MethodProgram/UMM")
    if not isinstance(machine_kind, MachineKind) or machine_kind is MachineKind.METHOD:
        raise ValueError("callable machine lowering requires non-Method MachineKind")
    if definition.implementation is None:
        raise ResearchImplementationResolutionError(
            "paper callable definition has no implementation"
        )
    if resolved is not None and resolver is not None:
        raise ValueError("machine lowering accepts resolved or resolver, not both")
    selected = (
        resolved
        if resolved is not None
        else (
            resolver
            if resolver is not None
            else ImportResearchImplementationResolver()
        ).resolve(definition)
    )
    if (
        selected.definition_id != definition.definition_id
        or selected.declared != definition.implementation
    ):
        raise ResearchImplementationResolutionError(
            "resolved machine implementation does not match frozen definition"
        )
    implementation = selected.implementation
    accepts_payload = _plain_callable_accepts_payload(implementation)
    operation_name = (
        f"research-os.{machine_kind.value}:{definition.definition_id}"
    )

    def handle(request: ProgramNodeRequest, _binding: object) -> ProgramNodeResult:
        value = _invoke_plain_callable(
            implementation,
            accepts_payload=accepts_payload,
            payload=request.payload,
        )
        if type(value) is ProgramNodeResult:
            return value
        return ProgramNodeResult(value=value)

    config_value = definition.config
    configuration = (
        dict(config_value)
        if isinstance(config_value, Mapping)
        else {"research_definition_config": config_value}
    )
    configuration["research_definition_id"] = definition.definition_id
    configuration["research_implementation_digest"] = (
        selected.declared.implementation_digest
    )
    builder = MachineResearchProgramBuilder(
        program_id=f"research-os:{machine_kind.value}:{definition.definition_id}",
        kind=machine_kind,
        version=selected.declared.source_digest,
        state_schema="json",
        entrypoint="invoke",
    )
    builder.node(
        "invoke",
        operation_name,
        configuration=configuration,
    )
    program = builder.build()
    operation = ResearchHostOperation(
        operation_name,
        handle,
        selected.declared.implementation_digest,
    )
    return LoweredResearchMachineProgram(
        definition.definition_id,
        machine_kind,
        program,
        operation,
    )


@dataclass(frozen=True, slots=True)
class LoweredResearchMethodProgram:
    """One METHOD definition compiled to the canonical UMM program IR."""

    definition_id: str
    program: MethodProgram

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError("lowered method definition_id is required")
        if type(self.program) is not MethodProgram:
            raise TypeError("lowered method requires MethodProgram")


@dataclass(frozen=True, slots=True)
class LoweredResearchOSGraphNode:
    """Ephemeral executable lowering view over an immutable ResearchGraph node."""

    source: CompiledResearchOSGraphNode
    target: ResearchOSLoweringTarget
    implementations: tuple[
        ResolvedResearchImplementation | ResolvedResearchMethodProgramImplementation,
        ...,
    ] = ()
    platform_requirements: tuple[ResearchDefinition, ...] = ()
    method_programs: tuple[LoweredResearchMethodProgram, ...] = ()
    machine_programs: tuple[LoweredResearchMachineProgram, ...] = ()
    experiment_closure: ResearchOSExperimentClosure | None = None
    lowering_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.source) is not CompiledResearchOSGraphNode:
            raise TypeError("lowered Research OS node requires compiled graph node")
        if not isinstance(self.target, ResearchOSLoweringTarget):
            raise TypeError("lowered Research OS target must be typed")
        if type(self.implementations) is not tuple or any(
            type(row)
            not in {
                ResolvedResearchImplementation,
                ResolvedResearchMethodProgramImplementation,
            }
            for row in self.implementations
        ):
            raise TypeError("lowered implementations must be a typed tuple")
        if type(self.platform_requirements) is not tuple or any(
            type(row) is not ResearchDefinition
            for row in self.platform_requirements
        ):
            raise TypeError("lowered platform requirements must be ResearchDefinition tuple")
        if type(self.method_programs) is not tuple or any(
            type(row) is not LoweredResearchMethodProgram
            for row in self.method_programs
        ):
            raise TypeError("lowered method programs must be typed tuple")
        if type(self.machine_programs) is not tuple or any(
            type(row) is not LoweredResearchMachineProgram
            for row in self.machine_programs
        ):
            raise TypeError("lowered machine programs must be typed tuple")
        if self.experiment_closure is not None and type(
            self.experiment_closure
        ) is not ResearchOSExperimentClosure:
            raise TypeError("lowered experiment closure must be typed")

        definitions = {row.definition_id: row for row in self.source.definitions}
        implementation_ids = tuple(row.definition_id for row in self.implementations)
        requirement_ids = tuple(row.definition_id for row in self.platform_requirements)
        method_ids = tuple(row.definition_id for row in self.method_programs)
        machine_ids = tuple(row.definition_id for row in self.machine_programs)
        if len(implementation_ids) != len(set(implementation_ids)):
            raise ValueError("lowered implementation definitions must be unique")
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("lowered platform requirements must be unique")
        if set(implementation_ids) & set(requirement_ids):
            raise ValueError("one research definition cannot be both implementation and requirement")
        if set(implementation_ids) | set(requirement_ids) != set(definitions):
            raise ValueError("lowered definitions must partition source definitions")
        if any(definitions[key].implementation is None for key in implementation_ids):
            raise ValueError("implementation lowering contains platform-resolved definition")
        if any(definitions[key].implementation is not None for key in requirement_ids):
            raise ValueError("platform requirement contains paper implementation")
        if len(method_ids) != len(set(method_ids)):
            raise ValueError("lowered method program definitions must be unique")
        if any(key not in implementation_ids for key in method_ids):
            raise ValueError("lowered method program must belong to an implementation")
        if any(
            definitions[key].kind is not ResearchDefinitionKind.METHOD
            for key in method_ids
        ):
            raise ValueError("only METHOD definitions may lower to MethodProgram")
        if len(machine_ids) != len(set(machine_ids)):
            raise ValueError("lowered machine program definitions must be unique")
        if any(key not in implementation_ids for key in machine_ids):
            raise ValueError("lowered machine program must belong to an implementation")
        if any(
            definitions[key].kind is ResearchDefinitionKind.METHOD
            for key in machine_ids
        ):
            raise ValueError("METHOD definitions cannot lower to ResearchProgram")
        expected_machine_kind = _NODE_MACHINE_KINDS.get(self.source.node.kind)
        if self.machine_programs and expected_machine_kind is None:
            raise ValueError("node kind does not own a programmable ResearchProgram target")
        if expected_machine_kind is not None and any(
            row.machine_kind is not expected_machine_kind
            for row in self.machine_programs
        ):
            raise ValueError("lowered machine program kind does not match node target")
        executable_ids = set(method_ids) | set(machine_ids)
        if self.target is ResearchOSLoweringTarget.EXPERIMENTATION:
            if self.experiment_closure is None:
                raise ResearchOSExperimentClosureMissing(
                    "Experimentation node requires a complete canonical experiment closure"
                )
            if executable_ids:
                raise ValueError(
                    "Experimentation node cannot also carry per-definition Machine programs"
                )
        else:
            if self.experiment_closure is not None:
                raise ValueError(
                    "non-Experimentation node cannot carry an experiment closure"
                )
            if executable_ids != set(implementation_ids):
                missing = tuple(sorted(set(implementation_ids) - executable_ids))
                extra = tuple(sorted(executable_ids - set(implementation_ids)))
                raise ValueError(
                    "paper implementations must lower exactly once to executable "
                    f"Machine IR; missing={missing}, extra={extra}"
                )

        ordered_implementations = tuple(
            sorted(self.implementations, key=lambda row: row.definition_id)
        )
        ordered_requirements = tuple(
            sorted(self.platform_requirements, key=lambda row: row.definition_id)
        )
        ordered_method_programs = tuple(
            sorted(self.method_programs, key=lambda row: row.definition_id)
        )
        ordered_machine_programs = tuple(
            sorted(self.machine_programs, key=lambda row: row.definition_id)
        )
        object.__setattr__(self, "implementations", ordered_implementations)
        object.__setattr__(self, "platform_requirements", ordered_requirements)
        object.__setattr__(self, "method_programs", ordered_method_programs)
        object.__setattr__(self, "machine_programs", ordered_machine_programs)
        object.__setattr__(
            self,
            "lowering_digest",
            canonical_digest(
                {
                    "source_semantic_digest": self.source.semantic_digest,
                    "target": self.target.value,
                    "implementations": tuple(
                        (
                            row.definition_id,
                            row.declared.implementation_digest,
                        )
                        for row in ordered_implementations
                    ),
                    "platform_requirements": tuple(
                        (
                            row.definition_id,
                            row.definition_digest,
                        )
                        for row in ordered_requirements
                    ),
                    "method_programs": tuple(
                        (row.definition_id, row.program.program_digest)
                        for row in ordered_method_programs
                    ),
                    "machine_programs": tuple(
                        (
                            row.definition_id,
                            row.machine_kind.value,
                            row.program.program_digest,
                            row.operation.implementation_digest,
                        )
                        for row in ordered_machine_programs
                    ),
                    "experiment_closure_digest": (
                        None
                        if self.experiment_closure is None
                        else self.experiment_closure.closure_digest
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchOSLoweringPlan:
    graph_id: str
    graph_digest: str
    research_revision_digest: str
    nodes: tuple[LoweredResearchOSGraphNode, ...]
    lowering_digest: str = field(init=False)
    _node_ids: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.graph_id) is not str or not self.graph_id.strip():
            raise ValueError("Research OS lowering graph_id is required")
        for name, value in (
            ("graph_digest", self.graph_digest),
            ("research_revision_digest", self.research_revision_digest),
        ):
            if type(value) is not str or len(value) != 64:
                raise ValueError(f"Research OS lowering {name} must be sha256 text")
        if type(self.nodes) is not tuple or not self.nodes or any(
            type(node) is not LoweredResearchOSGraphNode for node in self.nodes
        ):
            raise TypeError("Research OS lowering nodes must be a non-empty typed tuple")
        ordered = tuple(sorted(self.nodes, key=lambda row: row.source.graph_node_id))
        ids = tuple(row.source.graph_node_id for row in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("Research OS lowering graph node ids must be unique")
        object.__setattr__(self, "nodes", ordered)
        object.__setattr__(self, "_node_ids", ids)
        object.__setattr__(
            self,
            "lowering_digest",
            canonical_digest(
                {
                    "graph_id": self.graph_id,
                    "graph_digest": self.graph_digest,
                    "research_revision_digest": self.research_revision_digest,
                    "nodes": tuple(
                        (row.source.graph_node_id, row.lowering_digest)
                        for row in ordered
                    ),
                }
            ),
        )

    def node(self, graph_node_id: str) -> LoweredResearchOSGraphNode:
        if type(graph_node_id) is not str or not graph_node_id:
            raise KeyError(graph_node_id)
        index = bisect_left(self._node_ids, graph_node_id)
        if index >= len(self._node_ids) or self._node_ids[index] != graph_node_id:
            raise KeyError(graph_node_id)
        return self.nodes[index]


class ResearchOSLoweringCompiler:
    """Compile canonical ResearchGraph nodes toward existing lower authorities."""

    def __init__(
        self,
        resolver: ResearchImplementationResolverPort | None = None,
        experiment_closures: ResearchOSExperimentClosurePort | None = None,
    ) -> None:
        resolved = (
            resolver
            if resolver is not None
            else ImportResearchImplementationResolver()
        )
        if not isinstance(resolved, ResearchImplementationResolverPort):
            raise TypeError(
                "Research OS lowering resolver must satisfy "
                "ResearchImplementationResolverPort"
            )
        self._resolver = resolved
        if experiment_closures is not None and not isinstance(
            experiment_closures,
            ResearchOSExperimentClosurePort,
        ):
            raise TypeError(
                "Research OS experiment closure resolver must satisfy "
                "ResearchOSExperimentClosurePort"
            )
        self._experiment_closures = experiment_closures

    def compile_node(
        self,
        node: CompiledResearchOSGraphNode,
        *,
        graph_id: str | None = None,
        graph_digest: str | None = None,
        research_revision_digest: str | None = None,
    ) -> LoweredResearchOSGraphNode:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("Research OS lowering requires CompiledResearchOSGraphNode")
        target = _NODE_TARGETS[node.node.kind]
        implementations: list[
            ResolvedResearchImplementation | ResolvedResearchMethodProgramImplementation
        ] = []
        requirements: list[ResearchDefinition] = []
        method_programs: list[LoweredResearchMethodProgram] = []
        machine_programs: list[LoweredResearchMachineProgram] = []
        for definition in node.definitions:
            if definition.implementation is None:
                requirements.append(definition)
                continue
            if type(definition.implementation) is ResearchMethodProgramImplementation:
                resolved_method = resolve_method_program_implementation(definition)
                implementations.append(resolved_method)
                if target is ResearchOSLoweringTarget.EXPERIMENTATION:
                    continue
                if target is not ResearchOSLoweringTarget.METHOD_MACHINE:
                    raise ResearchImplementationResolutionError(
                        "MethodProgram implementation may only execute through "
                        f"METHOD/Experimentation targets: node={node.graph_node_id}"
                    )
                method_programs.append(
                    LoweredResearchMethodProgram(
                        definition.definition_id,
                        resolved_method.program,
                    )
                )
                continue
            resolved = self._resolver.resolve(definition)
            implementations.append(resolved)
            if target is ResearchOSLoweringTarget.EXPERIMENTATION:
                continue
            if definition.kind is ResearchDefinitionKind.METHOD:
                method_programs.append(
                    LoweredResearchMethodProgram(
                        definition.definition_id,
                        compile_callable_method_definition(
                            definition,
                            resolved=resolved,
                        ),
                    )
                )
                continue
            machine_kind = _NODE_MACHINE_KINDS.get(node.node.kind)
            if machine_kind is None:
                raise ResearchImplementationResolutionError(
                    "research node has a paper implementation but no "
                    "canonical Machine lowering target: "
                    f"node={node.graph_node_id} "
                    f"kind={node.node.kind.value} "
                    f"definition={definition.definition_id}"
                )
            machine_programs.append(
                compile_callable_machine_definition(
                    definition,
                    machine_kind=machine_kind,
                    resolved=resolved,
                )
            )

        experiment_closure = None
        if target is ResearchOSLoweringTarget.EXPERIMENTATION:
            if (
                graph_id is None
                or graph_digest is None
                or research_revision_digest is None
            ):
                raise ResearchOSExperimentClosureMissing(
                    "Experimentation lowering requires complete ResearchGraph identity"
                )
            if self._experiment_closures is None:
                raise ResearchOSExperimentClosureMissing(
                    "Experimentation lowering requires an explicit canonical "
                    "experiment closure provider"
                )
            experiment_closure = self._experiment_closures.resolve(
                graph_id=graph_id,
                graph_digest=graph_digest,
                research_revision_digest=research_revision_digest,
                node=node,
            )
            if type(experiment_closure) is not ResearchOSExperimentClosure:
                raise TypeError(
                    "experiment closure provider returned an invalid closure"
                )
            experiment_closure.validate_source(
                graph_id=graph_id,
                graph_digest=graph_digest,
                research_revision_digest=research_revision_digest,
                node=node,
            )

        return LoweredResearchOSGraphNode(
            source=node,
            target=target,
            implementations=tuple(implementations),
            platform_requirements=tuple(requirements),
            method_programs=tuple(method_programs),
            machine_programs=tuple(machine_programs),
            experiment_closure=experiment_closure,
        )

    def compile(
        self,
        compilation: CompiledResearchOSGraph,
        *,
        selected_node_ids: tuple[str, ...] | None = None,
    ) -> ResearchOSLoweringPlan:
        if type(compilation) is not CompiledResearchOSGraph:
            raise TypeError("Research OS lowering requires CompiledResearchOSGraph")
        nodes = compilation.nodes
        if selected_node_ids is not None:
            if type(selected_node_ids) is not tuple or not selected_node_ids or any(
                type(node_id) is not str or not node_id.strip()
                for node_id in selected_node_ids
            ):
                raise TypeError("Research OS lowering selection must be a non-empty text tuple")
            selected = set(selected_node_ids)
            if len(selected) != len(selected_node_ids):
                raise ValueError("Research OS lowering selection node ids must be unique")
            known = {node.graph_node_id for node in compilation.nodes}
            unknown = tuple(sorted(selected - known))
            if unknown:
                raise ValueError(
                    f"Research OS lowering selection references unknown nodes: {unknown}"
                )
            nodes = tuple(
                node for node in compilation.nodes if node.graph_node_id in selected
            )
        return ResearchOSLoweringPlan(
            compilation.plan.graph_id,
            compilation.plan.graph_digest,
            compilation.plan.research_revision_digest,
            tuple(
                self.compile_node(
                    node,
                    graph_id=compilation.plan.graph_id,
                    graph_digest=compilation.plan.graph_digest,
                    research_revision_digest=(
                        compilation.plan.research_revision_digest
                    ),
                )
                for node in nodes
            ),
        )


def compile_research_os_lowering(
    compilation: CompiledResearchOSGraph,
    *,
    resolver: ResearchImplementationResolverPort | None = None,
    experiment_closures: ResearchOSExperimentClosurePort | None = None,
    selected_node_ids: tuple[str, ...] | None = None,
) -> ResearchOSLoweringPlan:
    return ResearchOSLoweringCompiler(
        resolver,
        experiment_closures,
    ).compile(
        compilation,
        selected_node_ids=selected_node_ids,
    )


__all__ = [
    "ImportResearchImplementationResolver",
    "LoweredResearchMachineProgram",
    "LoweredResearchMethodProgram",
    "LoweredResearchOSGraphNode",
    "ResearchImplementationResolutionError",
    "ResearchImplementationResolverPort",
    "ResearchOSLoweringCompiler",
    "ResearchOSLoweringPlan",
    "ResearchOSLoweringTarget",
    "ResolvedResearchImplementation",
    "compile_callable_machine_definition",
    "compile_callable_method_definition",
    "compile_research_os_lowering",
]
