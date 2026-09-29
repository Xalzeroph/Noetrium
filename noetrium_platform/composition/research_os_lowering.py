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
    thaw_json,
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
    ResearchMachineProgramImplementation,
    ResearchComponent,
    ResearchMethod,
    ResearchMethodImplementation,
    ResearchNodeKind,
)

from .research_definition_authority import (
    ResearchDefinitionBinding,
    ResearchDefinitionBindingAuthorityPort,
    ResearchDefinitionBindingMissing,
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
class ResolvedResearchMethodImplementation:
    definition_id: str
    declared: ResearchMethodImplementation
    method: ResearchMethod

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError("resolved ResearchMethod definition_id is required")
        if type(self.declared) is not ResearchMethodImplementation:
            raise TypeError("resolved ResearchMethod requires typed declaration")
        if type(self.method) is not ResearchMethod:
            raise TypeError("resolved ResearchMethod requires ResearchMethod artifact")
        if self.method.artifact_digest != self.declared.method_digest:
            raise ValueError("resolved ResearchMethod digest drifted from declaration")


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


def resolve_research_method_implementation(
    definition: ResearchDefinition,
) -> ResolvedResearchMethodImplementation:
    if type(definition) is not ResearchDefinition:
        raise TypeError("ResearchMethod resolution requires ResearchDefinition")
    if definition.kind is not ResearchDefinitionKind.METHOD:
        raise ValueError("ResearchMethod resolution requires METHOD definition")
    declared = definition.implementation
    if type(declared) is not ResearchMethodImplementation:
        raise TypeError(
            "METHOD definition requires ResearchMethodImplementation"
        )
    try:
        method = declared.resolve()
    except Exception as exc:
        raise ResearchImplementationResolutionError(
            "research method could not be reconstructed from frozen identity: "
            f"{declared.module}:{declared.qualname}"
        ) from exc
    return ResolvedResearchMethodImplementation(
        definition.definition_id,
        declared,
        method,
    )


@dataclass(frozen=True, slots=True)
class ResolvedResearchMachineProgramImplementation:
    """Resolved immutable native ResearchProgram and exact operation set."""

    definition_id: str
    declared: ResearchMachineProgramImplementation
    program: MachineResearchProgram
    operations: tuple[ResearchHostOperation, ...]

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError(
                "resolved ResearchProgram implementation definition_id is required"
            )
        if type(self.declared) is not ResearchMachineProgramImplementation:
            raise TypeError(
                "resolved ResearchProgram implementation requires typed declaration"
            )
        if type(self.program) is not MachineResearchProgram:
            raise TypeError(
                "resolved ResearchProgram implementation requires exact ResearchProgram"
            )
        if type(self.operations) is not tuple or any(
            type(row) is not ResearchHostOperation for row in self.operations
        ):
            raise TypeError(
                "resolved ResearchProgram operations must be ResearchHostOperation tuple"
            )
        if self.program.program_digest != self.declared.program_digest:
            raise ValueError(
                "resolved ResearchProgram digest drifted from immutable declaration"
            )
        if self.program.kind.value != self.declared.machine_kind:
            raise ValueError(
                "resolved ResearchProgram machine kind drifted from declaration"
            )
        identities = tuple(
            sorted(
                (row.operation, row.implementation_digest)
                for row in self.operations
            )
        )
        if identities != self.declared.operation_identities:
            raise ValueError(
                "resolved ResearchProgram operation identity set drifted"
            )
        if canonical_digest(identities) != self.declared.operations_digest:
            raise ValueError(
                "resolved ResearchProgram operation digest drifted"
            )


def resolve_machine_program_implementation(
    definition: ResearchDefinition,
) -> ResolvedResearchMachineProgramImplementation:
    """Resolve native ResearchProgram + operation set and prove exact identity."""

    if type(definition) is not ResearchDefinition:
        raise TypeError("ResearchProgram resolution requires ResearchDefinition")
    declared = definition.implementation
    if type(declared) is not ResearchMachineProgramImplementation:
        raise TypeError(
            "ResearchProgram resolution requires ResearchMachineProgramImplementation"
        )
    try:
        program: object = importlib.import_module(declared.program_module)
        for part in declared.program_qualname.split("."):
            program = getattr(program, part)
        operation_factory: object = importlib.import_module(
            declared.operations_module
        )
        for part in declared.operations_qualname.split("."):
            operation_factory = getattr(operation_factory, part)
    except (ImportError, AttributeError) as exc:
        raise ResearchImplementationResolutionError(
            "native ResearchProgram binding can no longer be imported"
        ) from exc
    if type(program) is not MachineResearchProgram:
        raise ResearchImplementationResolutionError(
            "native ResearchProgram binding no longer resolves to ResearchProgram"
        )
    if not callable(operation_factory):
        raise ResearchImplementationResolutionError(
            "native ResearchProgram operation binding is not callable"
        )
    try:
        operations = operation_factory()
    except Exception as exc:
        raise ResearchImplementationResolutionError(
            "native ResearchProgram operation factory failed to materialize"
        ) from exc
    if type(operations) is not tuple or any(
        type(row) is not ResearchHostOperation for row in operations
    ):
        raise ResearchImplementationResolutionError(
            "native ResearchProgram operation factory must return exact "
            "ResearchHostOperation tuple"
        )
    resolved = ResolvedResearchMachineProgramImplementation(
        definition.definition_id,
        declared,
        program,
        operations,
    )
    return resolved


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



@dataclass(frozen=True, slots=True)
class LoweredResearchMachineProgram:
    """One native programmable ResearchProgram plus its exact operation set."""

    definition_id: str
    machine_kind: MachineKind
    program: MachineResearchProgram
    operations: tuple[ResearchHostOperation, ...]

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
        if type(self.operations) is not tuple or any(
            type(row) is not ResearchHostOperation for row in self.operations
        ):
            raise TypeError(
                "lowered machine operations must be ResearchHostOperation tuple"
            )
        names = tuple(row.operation for row in self.operations)
        if len(names) != len(set(names)):
            raise ValueError("lowered machine operation names must be unique")
        required = {
            node.operation
            for node in self.program.nodes
            if not node.operation.startswith("core.")
        }
        if set(names) != required:
            raise ValueError(
                "lowered machine operation closure must exactly match program"
            )

    @property
    def operations_digest(self) -> str:
        return canonical_digest(
            tuple(
                sorted(
                    (row.operation, row.implementation_digest)
                    for row in self.operations
                )
            )
        )


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
        (operation,),
    )


@dataclass(frozen=True, slots=True)
class LoweredResearchMethodProgram:
    """One METHOD definition compiled to the canonical UMM program IR."""

    definition_id: str
    program: MethodProgram
    components: tuple[ResearchComponent, ...] = ()

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError("lowered method definition_id is required")
        if type(self.program) is not MethodProgram:
            raise TypeError("lowered method requires MethodProgram")
        if type(self.components) is not tuple or any(
            type(row) is not ResearchComponent for row in self.components
        ):
            raise TypeError(
                "lowered method components must be ResearchComponent tuple"
            )
        ordered = tuple(
            sorted(self.components, key=lambda row: (row.domain.value, row.host_id))
        )
        if len({row.host_id for row in ordered}) != len(ordered):
            raise ValueError("lowered method component host ids must be unique")
        object.__setattr__(self, "components", ordered)


@dataclass(frozen=True, slots=True)
class LoweredResearchOSGraphNode:
    """Ephemeral executable lowering view over an immutable ResearchGraph node."""

    source: CompiledResearchOSGraphNode
    target: ResearchOSLoweringTarget
    implementations: tuple[
        ResolvedResearchImplementation
        | ResolvedResearchMethodImplementation
        | ResolvedResearchMachineProgramImplementation,
        ...,
    ] = ()
    platform_bindings: tuple[ResearchDefinitionBinding, ...] = ()
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
                ResolvedResearchMethodImplementation,
                ResolvedResearchMachineProgramImplementation,
            }
            for row in self.implementations
        ):
            raise TypeError("lowered implementations must be a typed tuple")
        if type(self.platform_bindings) is not tuple or any(
            type(row) is not ResearchDefinitionBinding
            for row in self.platform_bindings
        ):
            raise TypeError("lowered platform bindings must be typed tuple")
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
        platform_binding_ids = tuple(row.definition_id for row in self.platform_bindings)
        requirement_ids = tuple(row.definition_id for row in self.platform_requirements)
        method_ids = tuple(row.definition_id for row in self.method_programs)
        machine_ids = tuple(row.definition_id for row in self.machine_programs)
        if len(implementation_ids) != len(set(implementation_ids)):
            raise ValueError("lowered implementation definitions must be unique")
        if len(platform_binding_ids) != len(set(platform_binding_ids)):
            raise ValueError("lowered platform bindings must be unique")
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("lowered platform requirements must be unique")
        partitions = (
            set(implementation_ids),
            set(platform_binding_ids),
            set(requirement_ids),
        )
        if any(partitions[i] & partitions[j] for i in range(3) for j in range(i + 1, 3)):
            raise ValueError("one research definition cannot occupy two lowering partitions")
        if set().union(*partitions) != set(definitions):
            raise ValueError("lowered definitions must partition source definitions")
        if any(definitions[key].implementation is None for key in implementation_ids):
            raise ValueError("implementation lowering contains platform-resolved definition")
        if any(definitions[key].implementation is not None for key in requirement_ids):
            raise ValueError("platform requirement contains paper implementation")
        if any(definitions[key].implementation is not None for key in platform_binding_ids):
            raise ValueError("platform binding contains paper implementation")
        for row in self.platform_bindings:
            row.validate_definition(definitions[row.definition_id])
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
        ordered_platform_bindings = tuple(
            sorted(self.platform_bindings, key=lambda row: row.definition_id)
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
        object.__setattr__(self, "platform_bindings", ordered_platform_bindings)
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
                    "platform_bindings": tuple(
                        (
                            row.definition_id,
                            row.kind.value,
                            row.owner_system,
                            row.provider_identity,
                            row.binding_identity_digest,
                            row.binding_digest,
                        )
                        for row in ordered_platform_bindings
                    ),
                    "platform_requirements": tuple(
                        (
                            row.definition_id,
                            row.definition_digest,
                        )
                        for row in ordered_requirements
                    ),
                    "method_programs": tuple(
                        (
                            row.definition_id,
                            row.program.program_digest,
                            tuple(component.artifact_digest for component in row.components),
                        )
                        for row in ordered_method_programs
                    ),
                    "machine_programs": tuple(
                        (
                            row.definition_id,
                            row.machine_kind.value,
                            row.program.program_digest,
                            row.operations_digest,
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
        definition_bindings: ResearchDefinitionBindingAuthorityPort | None = None,
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
        if definition_bindings is not None and not isinstance(
            definition_bindings,
            ResearchDefinitionBindingAuthorityPort,
        ):
            raise TypeError(
                "Research OS definition bindings must satisfy "
                "ResearchDefinitionBindingAuthorityPort"
            )
        self._definition_bindings = definition_bindings

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
            ResolvedResearchImplementation
            | ResolvedResearchMethodImplementation
            | ResolvedResearchMachineProgramImplementation
        ] = []
        platform_bindings: list[ResearchDefinitionBinding] = []
        requirements: list[ResearchDefinition] = []
        method_programs: list[LoweredResearchMethodProgram] = []
        machine_programs: list[LoweredResearchMachineProgram] = []
        for definition in node.definitions:
            if definition.implementation is None:
                if self._definition_bindings is None:
                    requirements.append(definition)
                    continue
                try:
                    binding = self._definition_bindings.resolve(definition)
                except ResearchDefinitionBindingMissing:
                    requirements.append(definition)
                    continue
                platform_bindings.append(binding)
                continue
            if type(definition.implementation) is ResearchMachineProgramImplementation:
                if target is ResearchOSLoweringTarget.EXPERIMENTATION:
                    raise ResearchImplementationResolutionError(
                        "native ResearchProgram implementation cannot execute through "
                        f"Experimentation target: node={node.graph_node_id}"
                    )
                resolved_machine = resolve_machine_program_implementation(definition)
                implementations.append(resolved_machine)
                machine_programs.append(
                    LoweredResearchMachineProgram(
                        definition.definition_id,
                        resolved_machine.program.kind,
                        resolved_machine.program,
                        resolved_machine.operations,
                    )
                )
                continue
            if type(definition.implementation) is ResearchMethodImplementation:
                resolved_method = resolve_research_method_implementation(definition)
                implementations.append(resolved_method)
                if target is ResearchOSLoweringTarget.EXPERIMENTATION:
                    continue
                if target is not ResearchOSLoweringTarget.METHOD_MACHINE:
                    raise ResearchImplementationResolutionError(
                        "ResearchMethod may only execute through METHOD/Experimentation "
                        f"targets: node={node.graph_node_id}"
                    )
                method_programs.append(
                    LoweredResearchMethodProgram(
                        definition.definition_id,
                        resolved_method.method.program,
                        resolved_method.method.components,
                    )
                )
                continue
            resolved = self._resolver.resolve(definition)
            implementations.append(resolved)
            if target is ResearchOSLoweringTarget.EXPERIMENTATION:
                continue
            if definition.kind is ResearchDefinitionKind.METHOD:
                raise ResearchImplementationResolutionError(
                    "METHOD definitions must use ResearchMethodImplementation"
                )
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
            platform_bindings=tuple(platform_bindings),
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
    definition_bindings: ResearchDefinitionBindingAuthorityPort | None = None,
    selected_node_ids: tuple[str, ...] | None = None,
) -> ResearchOSLoweringPlan:
    return ResearchOSLoweringCompiler(
        resolver,
        experiment_closures,
        definition_bindings,
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
    "ResolvedResearchMachineProgramImplementation",
    "compile_callable_machine_definition",
    "compile_callable_method_definition",
    "compile_research_os_lowering",
    "resolve_machine_program_implementation",
]
