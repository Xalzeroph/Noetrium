from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.universal import UnitStepContext, UnitTransition

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import inspect
from typing import Callable, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import UnitOperationBinding, NoetriumUnit, unit_operation, executable_unit
from noetrium_platform.foundation.kernel.kernel.universal import (
    unit_operation_name,
    executable_unit_domain,
    validate_executable_unit,
    executable_unit_nodes,
)
from noetrium_platform.research.execution.workflow.runtime.program_lowering import (
    method_program_operations,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    NoetriumUnit,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.structure import (
    implementation_digest,
    implementation_field,
    is_implementation,
)
from noetrium_platform.product.research_implementation import (
    EXECUTABLE_UNIT_IMPLEMENTATION_TYPE,
    METHOD_IMPLEMENTATION_TYPE,
    PYTHON_IMPLEMENTATION_TYPE,
    resolve_executable_unit_implementation as resolve_executable_unit_unit,
    resolve_method_implementation as resolve_method_unit,
    resolve_python_implementation as resolve_python_unit,
)
from .research_semantics import (
    lowering_for_graph,
    platform_binding_traits,
    scientific_metadata_traits,
    trait_ids,
)
from noetrium_platform.product.research_traits import (
    TRAIT_ANALYSIS,
    TRAIT_METHOD,
    TRAIT_METRIC,
)
from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    require_research_plan,
    research_plan_digest,
    research_plan_study,
    research_plan_value,
)
from noetrium_platform.research.experimentation.api.program import (
    experiment_compilation_batch_digest,
    experiment_compilation_execution_graph,
    experiment_compilation_plan,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_study_unit,
    study_definition_digest,
)

from .research_symbol_authority import (
    ResearchSymbolBinding,
    ResearchSymbolBindingAuthorityPort,
    ResearchSymbolBindingMissing,
)
from .research_experiment import (
    ResearchExperimentCompilationMissing,
    ResearchExperimentCompilationPort,
)
from .research_execution_graph import (
    ResearchExecutionBinding,
    ResearchCompilationView,
)

from .research_scientific_analysis import (
    compile_declarative_analysis_program,
    compile_declarative_metric_program,
    compile_declarative_study_measurement_program,
)



class ResearchImplementationResolutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = {} if diagnostics is None else dict(diagnostics)


def _compiled_semantic_traits(
    node: ResearchExecutionBinding,
) -> tuple[str, ...]:
    return tuple(sorted(node.graph.trait_ids))


@dataclass(frozen=True, slots=True)
class ResearchSymbolRequirement:
    symbol: NoetriumUnit
    owner_trait_id: str
    requirement_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.symbol) is not NoetriumUnit:
            raise TypeError("research requirement symbol must be NoetriumUnit")
        if type(self.owner_trait_id) is not str or not self.owner_trait_id.strip():
            raise ValueError("research requirement owner_trait_id is required")
        if not self.symbol.has_trait(self.owner_trait_id):
            raise ValueError(
                "research requirement owner trait is not declared by symbol"
            )
        object.__setattr__(
            self,
            "requirement_digest",
            canonical_digest(
                {
                    "symbol_digest": self.symbol.symbol_digest,
                    "owner_trait_id": self.owner_trait_id,
                }
            ),
        )

    @property
    def symbol_id(self) -> str:
        return self.symbol.symbol_id

    @property
    def symbol_digest(self) -> str:
        return self.symbol.symbol_digest


@dataclass(frozen=True, slots=True)
class ResolvedResearchImplementation:
    symbol_id: str
    declared: NoetriumUnit
    implementation: Callable[..., object]

    def __post_init__(self) -> None:
        if type(self.symbol_id) is not str or not self.symbol_id.strip():
            raise ValueError("resolved research implementation symbol_id is required")
        if not is_implementation(self.declared, PYTHON_IMPLEMENTATION_TYPE):
            raise TypeError("resolved research implementation requires python implementation Unit")
        if not callable(self.implementation):
            raise TypeError("resolved research implementation value must be callable")


@dataclass(frozen=True, slots=True)
class ResolvedResearchMethodImplementation:
    symbol_id: str
    declared: NoetriumUnit
    method: NoetriumUnit

    def __post_init__(self) -> None:
        if type(self.symbol_id) is not str or not self.symbol_id.strip():
            raise ValueError("resolved ResearchMethod symbol_id is required")
        if not is_implementation(self.declared, METHOD_IMPLEMENTATION_TYPE):
            raise TypeError("resolved ResearchMethod requires method implementation Unit")
        if type(self.method) is not NoetriumUnit:
            raise TypeError("resolved research method requires NoetriumUnit")


@runtime_checkable
class ResearchImplementationResolverPort(Protocol):
    def resolve(
        self,
        definition: NoetriumUnit,
    ) -> ResolvedResearchImplementation: ...


class ImportResearchImplementationResolver:
    """Thin Research projection over the single implementation Unit resolver."""

    def resolve(
        self,
        definition: NoetriumUnit,
    ) -> ResolvedResearchImplementation:
        if type(definition) is not NoetriumUnit:
            raise TypeError("implementation resolution requires NoetriumUnit")
        declared = definition.implementation
        if declared is None:
            raise ResearchImplementationResolutionError(
                "definition is platform-resolved and has no paper implementation: "
                f"{definition.symbol_id}"
            )
        if not is_implementation(declared, PYTHON_IMPLEMENTATION_TYPE):
            raise ResearchImplementationResolutionError(
                f"definition {definition.symbol_id!r} is not a python implementation"
            )
        try:
            value = resolve_python_unit(declared)
        except Exception as exc:
            raise ResearchImplementationResolutionError(
                "research implementation could not be resolved from its frozen Unit"
            ) from exc
        return ResolvedResearchImplementation(
            definition.symbol_id,
            declared,
            value,
        )


def resolve_research_method_implementation(
    definition: NoetriumUnit,
) -> ResolvedResearchMethodImplementation:
    if type(definition) is not NoetriumUnit:
        raise TypeError("ResearchMethod resolution requires NoetriumUnit")
    if not definition.has_trait(TRAIT_METHOD):
        raise ValueError(
            "ResearchMethod resolution requires research.method symbol"
        )
    declared = definition.implementation
    if declared is None or not is_implementation(
        declared, METHOD_IMPLEMENTATION_TYPE
    ):
        raise TypeError("METHOD definition requires method implementation Unit")
    try:
        method = resolve_method_unit(declared)
    except Exception as exc:
        raise ResearchImplementationResolutionError(
            "research method could not be reconstructed from frozen implementation Unit",
            diagnostics={
                "definition_symbol_id": definition.symbol_id,
                "implementation_id": declared.unit_id,
                "implementation_digest": implementation_digest(declared),
                "implementation_type": implementation_field(
                    declared, "implementation_type", METHOD_IMPLEMENTATION_TYPE
                ),
                "module": implementation_field(declared, "module"),
                "qualname": implementation_field(declared, "qualname"),
                "expected_source_digest": implementation_field(
                    declared, "source_digest"
                ),
                "resolution_cause_type": type(exc).__qualname__,
                "resolution_cause_message": str(exc),
            },
        ) from exc
    return ResolvedResearchMethodImplementation(
        definition.symbol_id,
        declared,
        method,
    )


@dataclass(frozen=True, slots=True)
class ResolvedExecutableUnitImplementation:
    """Resolved immutable native Unit and exact operation set."""

    symbol_id: str
    declared: NoetriumUnit
    program: NoetriumUnit
    operations: tuple[UnitOperationBinding, ...]

    def __post_init__(self) -> None:
        if type(self.symbol_id) is not str or not self.symbol_id.strip():
            raise ValueError(
                "resolved Unit implementation symbol_id is required"
            )
        if not is_implementation(
            self.declared, EXECUTABLE_UNIT_IMPLEMENTATION_TYPE
        ):
            raise TypeError(
                "resolved Unit implementation requires machine-program implementation Unit"
            )
        if type(self.program) is not NoetriumUnit:
            raise TypeError(
                "resolved Unit implementation requires exact NoetriumUnit"
            )
        if type(self.operations) is not tuple or any(
            type(row) is not UnitOperationBinding for row in self.operations
        ):
            raise TypeError(
                "resolved Unit operations must be UnitOperationBinding tuple"
            )
        expected_program = implementation_field(self.declared, "program_digest")
        require_sha256(expected_program, "research machine expected program digest")
        if self.program.unit_digest != expected_program:
            raise ValueError(
                "resolved Unit digest drifted from immutable declaration"
            )
        expected_domain = str(
            implementation_field(self.declared, "domain")
        )
        if executable_unit_domain(self.program) != expected_domain:
            raise ValueError(
                "resolved Unit domain drifted from declaration"
            )
        identities = tuple(
            sorted(
                (row.operation, row.implementation_digest)
                for row in self.operations
            )
        )
        expected_identities = tuple(
            implementation_field(self.declared, "operation_identities", ())
        )
        if identities != expected_identities:
            raise ValueError(
                "resolved Unit operation identity set drifted"
            )
        expected_operations = implementation_field(
            self.declared, "operations_digest"
        )
        require_sha256(expected_operations, "research machine operations digest")
        if canonical_digest(identities) != expected_operations:
            raise ValueError(
                "resolved Unit operation digest drifted"
            )


def resolve_executable_unit_implementation(
    definition: NoetriumUnit,
) -> ResolvedExecutableUnitImplementation:
    """Resolve native Unit + operation set via the single product resolver."""

    if type(definition) is not NoetriumUnit:
        raise TypeError("Unit resolution requires NoetriumUnit")
    declared = definition.implementation
    if declared is None or not is_implementation(
        declared, EXECUTABLE_UNIT_IMPLEMENTATION_TYPE
    ):
        raise TypeError(
            "Unit resolution requires machine-program implementation Unit"
        )
    try:
        program, operations = resolve_executable_unit_unit(declared)
    except Exception as exc:
        raise ResearchImplementationResolutionError(
            "native Unit implementation could not be resolved"
        ) from exc
    return ResolvedExecutableUnitImplementation(
        definition.symbol_id,
        declared,
        program,
        tuple(operations),
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



@dataclass(frozen=True, slots=True)
class ResearchExecutableGraphBinding:
    """Runtime implementation closure for one exact executable NoetriumUnit."""

    symbol_id: str
    graph: NoetriumUnit
    domain: str
    operations: tuple[UnitOperationBinding, ...] = ()

    def __post_init__(self) -> None:
        if type(self.symbol_id) is not str or not self.symbol_id.strip():
            raise ValueError("executable Unit binding symbol_id is required")
        if type(self.graph) is not NoetriumUnit:
            raise TypeError("executable Unit binding requires NoetriumUnit")
        if type(self.domain) is not str or not self.domain.strip():
            raise ValueError("executable Unit binding domain is required")
        validate_executable_unit(self.graph)
        if executable_unit_domain(self.graph) != self.domain:
            raise ValueError("executable Unit domain drifted")
        if type(self.operations) is not tuple or any(
            type(row) is not UnitOperationBinding for row in self.operations
        ):
            raise TypeError("executable Unit operations must be UnitOperationBinding tuple")
        names = tuple(row.operation for row in self.operations)
        if len(names) != len(set(names)):
            raise ValueError("executable Unit operation names must be unique")
        required = {
            unit_operation_name(node)
            for node in executable_unit_nodes(self.graph)
            if not unit_operation_name(node).startswith("core.")
        }
        if set(names) != required:
            raise ValueError(
                "executable Unit implementation closure must exactly match graph; "
                f"required={tuple(sorted(required))} actual={tuple(sorted(names))}"
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


def compile_callable_unit_definition(
    definition: NoetriumUnit,
    *,
    domain: str,
    resolved: ResolvedResearchImplementation | None = None,
    resolver: ResearchImplementationResolverPort | None = None,
) -> ResearchExecutableGraphBinding:
    """Compile one non-Method paper callable into one executable graph binding."""

    if type(definition) is not NoetriumUnit:
        raise TypeError("callable machine lowering requires NoetriumUnit")
    if definition.has_trait(TRAIT_METHOD):
        raise ValueError("research.method symbol must lower through Method graph semantics")
    if type(domain) is not str or not domain.strip():
        raise ValueError("callable Unit lowering requires non-empty domain")
    domain = domain.strip()
    if definition.implementation is None:
        raise ResearchImplementationResolutionError(
            "paper callable definition has no implementation"
        )
    if resolved is not None and resolver is not None:
        raise ValueError("Unit lowering accepts resolved or resolver, not both")
    selected = (
        resolved
        if resolved is not None
        else (
            resolver if resolver is not None else ImportResearchImplementationResolver()
        ).resolve(definition)
    )
    if selected.symbol_id != definition.symbol_id or selected.declared != definition.implementation:
        raise ResearchImplementationResolutionError(
            "resolved Unit implementation does not match frozen definition"
        )
    implementation = selected.implementation
    accepts_payload = _plain_callable_accepts_payload(implementation)
    operation_name = f"research.{domain}:{definition.symbol_id}"

    def handle(request: UnitStepContext, _binding: object) -> UnitTransition:
        value = _invoke_plain_callable(
            implementation,
            accepts_payload=accepts_payload,
            payload=request.payload,
        )
        if type(value) is UnitTransition:
            return value
        return UnitTransition.goto(value=value)

    config_value = definition.parameters
    configuration = (
        dict(config_value)
        if isinstance(config_value, Mapping)
        else {"research_symbol_parameters": config_value}
    )
    configuration["research_symbol_id"] = definition.symbol_id
    configuration["research_implementation_digest"] = implementation_digest(selected.declared)
    graph = executable_unit(
        f"research:{domain}:{definition.symbol_id}",
        domain=domain,
        version=str(implementation_field(selected.declared, "source_digest")),
        state_schema="json",
        entrypoint="invoke",
        members=(
            unit_operation(
                "invoke",
                operation_name,
                configuration=configuration,
            ),
        ),
    )
    operation = UnitOperationBinding(
        operation_name,
        handle,
        implementation_digest(selected.declared),
    )
    return ResearchExecutableGraphBinding(
        definition.symbol_id,
        graph,
        domain,
        (operation,),
    )



@dataclass(frozen=True, slots=True)
class ResearchGraphExecutionBinding:
    """Compiler binding for one immutable scientific NoetriumUnit."""

    graph_node_id: str
    semantic_traits: tuple[str, ...]
    lowering_mode: str
    domain: str | None
    source_semantic_digest: str
    symbol_ids: tuple[str, ...] = ()
    implementations: tuple[
        ResolvedResearchImplementation
        | ResolvedResearchMethodImplementation
        | ResolvedExecutableUnitImplementation,
        ...,
    ] = ()
    platform_bindings: tuple[ResearchSymbolBinding, ...] = ()
    platform_requirements: tuple[ResearchSymbolRequirement, ...] = ()
    declarative_symbol_ids: tuple[str, ...] = ()
    metadata_symbol_ids: tuple[str, ...] = ()
    executables: tuple[ResearchExecutableGraphBinding, ...] = ()
    experiment_definition: NoetriumUnit | None = None
    experiment_binding: ResearchBindingContribution | None = None
    research_plan: NoetriumUnit | None = None
    experiment_program: NoetriumUnit | None = None
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.graph_node_id) is not str or not self.graph_node_id.strip():
            raise ValueError("research graph execution binding graph_node_id is required")
        if type(self.semantic_traits) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.semantic_traits
        ):
            raise TypeError("research execution semantic_traits must be text tuple")
        semantic_traits = tuple(sorted(set(self.semantic_traits)))
        if self.lowering_mode not in {"unit", "experimentation"}:
            raise ValueError("research execution lowering_mode is invalid")
        if (self.lowering_mode == "unit") != (self.domain is not None):
            raise ValueError("unit lowering requires exactly one semantic domain")
        if self.domain is not None and (
            type(self.domain) is not str or not self.domain.strip()
        ):
            raise ValueError("research execution domain must be non-empty text")
        require_sha256(self.source_semantic_digest, "research execution source_semantic_digest")

        symbol_ids = tuple(sorted(self.symbol_ids))
        if any(type(value) is not str or not value.strip() for value in symbol_ids):
            raise TypeError("research execution symbol_ids must be text")
        if len(symbol_ids) != len(set(symbol_ids)):
            raise ValueError("research execution symbol ids must be unique")
        if type(self.implementations) is not tuple or any(
            type(row) not in {
                ResolvedResearchImplementation,
                ResolvedResearchMethodImplementation,
                ResolvedExecutableUnitImplementation,
            }
            for row in self.implementations
        ):
            raise TypeError("research execution implementations must be typed tuple")
        if type(self.platform_bindings) is not tuple or any(
            type(row) is not ResearchSymbolBinding for row in self.platform_bindings
        ):
            raise TypeError("research execution platform bindings must be typed tuple")
        if type(self.platform_requirements) is not tuple or any(
            type(row) is not ResearchSymbolRequirement for row in self.platform_requirements
        ):
            raise TypeError("research execution platform requirements must be typed tuple")
        declarative_ids = tuple(sorted(self.declarative_symbol_ids))
        metadata_ids = tuple(sorted(self.metadata_symbol_ids))
        if len(declarative_ids) != len(set(declarative_ids)):
            raise ValueError("research declarative symbol ids must be unique")
        if len(metadata_ids) != len(set(metadata_ids)):
            raise ValueError("research metadata symbol ids must be unique")
        if type(self.executables) is not tuple or any(
            type(row) is not ResearchExecutableGraphBinding for row in self.executables
        ):
            raise TypeError("research execution executables must be typed tuple")
        experiment_fields = (
            self.experiment_definition,
            self.experiment_binding,
            self.research_plan,
            self.experiment_program,
        )
        experiment_present = tuple(row is not None for row in experiment_fields)
        if any(experiment_present) and not all(experiment_present):
            raise ValueError("Experimentation execution binding fields must be all present or all absent")

        ordered_impls = tuple(sorted(self.implementations, key=lambda row: row.symbol_id))
        ordered_bindings = tuple(sorted(
            self.platform_bindings,
            key=lambda row: (row.symbol_id, row.owner_trait_id),
        ))
        ordered_requirements = tuple(sorted(
            self.platform_requirements,
            key=lambda row: (row.symbol_id, row.owner_trait_id),
        ))
        ordered_execs = tuple(sorted(self.executables, key=lambda row: row.symbol_id))
        impl_ids = tuple(row.symbol_id for row in ordered_impls)
        exec_ids = tuple(row.symbol_id for row in ordered_execs)
        if len(impl_ids) != len(set(impl_ids)) or len(exec_ids) != len(set(exec_ids)):
            raise ValueError("research implementation/executable ids must be unique")
        platform_binding_keys = tuple(
            (row.symbol_id, row.owner_trait_id) for row in ordered_bindings
        )
        requirement_keys = tuple(
            (row.symbol_id, row.owner_trait_id) for row in ordered_requirements
        )
        if len(platform_binding_keys) != len(set(platform_binding_keys)):
            raise ValueError("research platform binding slots must be unique")
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("research platform requirement slots must be unique")
        platform_binding_ids = {row.symbol_id for row in ordered_bindings}
        requirement_ids = {row.symbol_id for row in ordered_requirements}
        impl_id_set = set(impl_ids)
        if impl_id_set & (platform_binding_ids | requirement_ids):
            raise ValueError("paper implementation cannot also be platform-resolved")
        if set(platform_binding_keys) & set(requirement_keys):
            raise ValueError("one platform slot cannot be both bound and unresolved")
        declarative_set = set(declarative_ids)
        metadata_set = set(metadata_ids)
        bound_ids = impl_id_set | platform_binding_ids | requirement_ids
        if declarative_set & bound_ids:
            raise ValueError("declarative symbol cannot own second binding authority")
        if metadata_set & (bound_ids | declarative_set):
            raise ValueError("metadata symbol cannot own executable authority")
        if bound_ids | declarative_set | metadata_set != set(symbol_ids):
            raise ValueError("execution bindings must cover every source symbol")

        if self.lowering_mode == "experimentation":
            if not all(experiment_present):
                raise ResearchExperimentCompilationMissing(
                    "Experimentation graph requires Unit-native compiled experiment fields"
                )
            if ordered_execs:
                raise ValueError("Experimentation graph cannot carry per-symbol executables")
            assert self.experiment_definition is not None
            assert self.experiment_binding is not None
            assert self.research_plan is not None
            assert self.experiment_program is not None
            require_study_unit(self.experiment_definition)
            if type(self.experiment_binding) is not ResearchBindingContribution:
                raise TypeError("Experimentation binding contribution must be typed")
            require_research_plan(self.research_plan)
            if (
                type(self.experiment_program) is not NoetriumUnit
                or not self.experiment_program.has_trait("experiment.compilation")
            ):
                raise TypeError("Experimentation program must be experiment.compilation Unit")
            if (
                research_plan_value(self.research_plan, "definition_digest")
                != study_definition_digest(self.experiment_definition)
            ):
                raise ValueError("Experimentation definition projection drifted")
            if (
                research_plan_value(self.research_plan, "binding_digest")
                != self.experiment_binding.contribution_digest
            ):
                raise ValueError("Experimentation binding contribution drifted")
            if experiment_compilation_plan(self.experiment_program) != research_plan_study(self.research_plan):
                raise ValueError("Experimentation program drifted from Research Plan Unit")
        else:
            if any(experiment_present):
                raise ValueError("non-Experimentation graph cannot carry experiment fields")
            expected = impl_id_set | declarative_set
            if set(exec_ids) != expected:
                raise ValueError(
                    "paper implementations/declarative symbols must map exactly once "
                    f"to executable graphs; expected={tuple(sorted(expected))}, "
                    f"actual={tuple(sorted(exec_ids))}"
                )
            if any(row.domain != self.domain for row in ordered_execs):
                raise ValueError("executable Unit domain drifted from research semantics")

        object.__setattr__(self, "semantic_traits", semantic_traits)
        object.__setattr__(self, "symbol_ids", symbol_ids)
        object.__setattr__(self, "implementations", ordered_impls)
        object.__setattr__(self, "platform_bindings", ordered_bindings)
        object.__setattr__(self, "platform_requirements", ordered_requirements)
        object.__setattr__(self, "declarative_symbol_ids", declarative_ids)
        object.__setattr__(self, "metadata_symbol_ids", metadata_ids)
        object.__setattr__(self, "executables", ordered_execs)
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "graph_node_id": self.graph_node_id,
                    "source_semantic_digest": self.source_semantic_digest,
                    "semantic_traits": semantic_traits,
                    "lowering_mode": self.lowering_mode,
                    "domain": self.domain,
                    "symbols": symbol_ids,
                    "implementations": tuple(
                        (row.symbol_id, implementation_digest(row.declared))
                        for row in ordered_impls
                    ),
                    "platform_bindings": tuple(
                        (row.symbol_id, row.owner_trait_id, row.binding_digest)
                        for row in ordered_bindings
                    ),
                    "platform_requirements": tuple(
                        (row.symbol_id, row.owner_trait_id, row.requirement_digest)
                        for row in ordered_requirements
                    ),
                    "declarative_symbols": declarative_ids,
                    "metadata_symbols": metadata_ids,
                    "executables": tuple(
                        (
                            row.symbol_id,
                            row.graph.unit_digest,
                            row.domain,
                            row.operations_digest,
                        )
                        for row in ordered_execs
                    ),
                    "experiment": (
                        None
                        if self.research_plan is None
                        else {
                            "definition_digest": study_definition_digest(self.experiment_definition),
                            "binding_digest": self.experiment_binding.contribution_digest,
                            "research_plan_digest": research_plan_digest(self.research_plan),
                            "experiment_execution_graph_digest": (
                                experiment_compilation_execution_graph(self.experiment_program).unit_digest
                            ),
                            "experiment_batch_plan_digest": (
                                experiment_compilation_batch_digest(self.experiment_program)
                            ),
                        }
                    ),
                }
            ),
        )

    def validate_source(self, node: ResearchExecutionBinding) -> None:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("research execution binding source must be compiled graph vertex")
        semantics = lowering_for_graph(node.graph)
        semantic_traits = _compiled_semantic_traits(node)
        if (
            self.graph_node_id != node.graph_node_id
            or self.source_semantic_digest != node.semantic_digest
            or self.semantic_traits != semantic_traits
            or self.lowering_mode != semantics.mode
            or self.domain != semantics.domain
        ):
            raise ValueError(
                "research execution binding source identity drifted: "
                f"graph={node.graph_node_id}"
            )


def research_execution_bindings_digest(
    compilation: ResearchCompilationView,
    bindings: tuple[ResearchGraphExecutionBinding, ...],
) -> str:
    if type(compilation) is not ResearchCompilationView:
        raise TypeError("execution binding digest requires compiled Research execution graph")
    if type(bindings) is not tuple or not bindings or any(
        type(row) is not ResearchGraphExecutionBinding for row in bindings
    ):
        raise TypeError("execution binding digest requires non-empty typed tuple")
    ordered = tuple(sorted(bindings, key=lambda row: row.graph_node_id))
    ids = tuple(row.graph_node_id for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("research execution binding graph ids must be unique")
    for binding in ordered:
        source = compilation.binding(binding.graph_node_id)
        binding.validate_source(source)
    return canonical_digest(
        {
            "graph_id": compilation.graph_id,
            "graph_digest": compilation.graph_digest,
            "research_revision_digest": compilation.research_revision_digest,
            "bindings": tuple(
                (row.graph_node_id, row.binding_digest) for row in ordered
            ),
        }
    )


class ResearchExecutionBindingCompiler:
    """Resolve compiled scientific nodes into executable bindings."""

    def __init__(
        self,
        resolver: ResearchImplementationResolverPort | None = None,
        experiment_compilation: ResearchExperimentCompilationPort | None = None,
        symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
    ) -> None:
        resolved = (
            resolver
            if resolver is not None
            else ImportResearchImplementationResolver()
        )
        if not isinstance(resolved, ResearchImplementationResolverPort):
            raise TypeError(
                "Research execution lowering resolver must satisfy "
                "ResearchImplementationResolverPort"
            )
        self._resolver = resolved
        if experiment_compilation is not None and not isinstance(
            experiment_compilation,
            ResearchExperimentCompilationPort,
        ):
            raise TypeError(
                "Research execution Experiment compiler must satisfy "
                "ResearchExperimentCompilationPort"
            )
        self._experiment_compilation = experiment_compilation
        if symbol_bindings is not None and not isinstance(
            symbol_bindings,
            ResearchSymbolBindingAuthorityPort,
        ):
            raise TypeError(
                "Research execution definition bindings must satisfy "
                "ResearchSymbolBindingAuthorityPort"
            )
        self._symbol_bindings = symbol_bindings
        # One compiler instance serves one immutable ResearchCompilationView.
        # Repeated symbols across experiment nodes therefore share exact
        # implementation resolution. Keys include symbol identity and frozen
        # implementation Unit identity so no distinct scientific definition can
        # collapse merely because it uses the same Python/configurer template.
        self._resolved_methods: dict[
            tuple[str, str], ResolvedResearchMethodImplementation
        ] = {}
        self._resolved_units: dict[
            tuple[str, str], ResolvedExecutableUnitImplementation
        ] = {}
        self._resolved_callables: dict[
            tuple[str, str], ResolvedResearchImplementation
        ] = {}

    def _resolve_method_once(
        self,
        definition: NoetriumUnit,
    ) -> ResolvedResearchMethodImplementation:
        implementation = definition.implementation
        if implementation is None:
            raise ResearchImplementationResolutionError(
                "METHOD definition lost immutable implementation"
            )
        key = (definition.symbol_id, implementation.unit_digest)
        cached = self._resolved_methods.get(key)
        if cached is not None:
            return cached
        resolved = resolve_research_method_implementation(definition)
        current = self._resolved_methods.setdefault(key, resolved)
        if current.method.unit_digest != resolved.method.unit_digest:
            raise RuntimeError(
                "immutable Method implementation resolved to multiple Unit identities"
            )
        return current

    def _resolve_unit_once(
        self,
        definition: NoetriumUnit,
    ) -> ResolvedExecutableUnitImplementation:
        implementation = definition.implementation
        if implementation is None:
            raise ResearchImplementationResolutionError(
                "executable Unit definition lost immutable implementation"
            )
        key = (definition.symbol_id, implementation.unit_digest)
        cached = self._resolved_units.get(key)
        if cached is not None:
            return cached
        resolved = resolve_executable_unit_implementation(definition)
        current = self._resolved_units.setdefault(key, resolved)
        if (
            current.program.unit_digest != resolved.program.unit_digest
            or current.operations_digest != resolved.operations_digest
        ):
            raise RuntimeError(
                "immutable executable Unit resolved to multiple identities"
            )
        return current

    def _resolve_callable_once(
        self,
        definition: NoetriumUnit,
    ) -> ResolvedResearchImplementation:
        implementation = definition.implementation
        if implementation is None:
            raise ResearchImplementationResolutionError(
                "paper implementation definition lost immutable implementation"
            )
        key = (definition.symbol_id, implementation.unit_digest)
        cached = self._resolved_callables.get(key)
        if cached is not None:
            return cached
        resolved = self._resolver.resolve(definition)
        current = self._resolved_callables.setdefault(key, resolved)
        return current

    def compile_node(
        self,
        node: ResearchExecutionBinding,
        *,
        graph_id: str | None = None,
        graph_digest: str | None = None,
        research_revision_digest: str | None = None,
    ) -> ResearchGraphExecutionBinding:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("research execution binding requires ResearchExecutionBinding")
        semantics = lowering_for_graph(node.graph)
        semantic_traits = _compiled_semantic_traits(node)
        implementations: list[
            ResolvedResearchImplementation
            | ResolvedResearchMethodImplementation
            | ResolvedExecutableUnitImplementation
        ] = []
        platform_bindings: list[ResearchSymbolBinding] = []
        requirements: list[ResearchSymbolRequirement] = []
        declarative_symbols: list[str] = []
        metadata_symbols: list[str] = []
        executables: list[ResearchExecutableGraphBinding] = []
        for definition in node.symbols:
            config = (
                definition.parameters
                if isinstance(definition.parameters, Mapping)
                else {}
            )
            if (
                semantics.mode == "experimentation"
                and definition.implementation is None
                and definition.has_trait(TRAIT_METRIC)
                and "measurement" in config
            ):
                declarative_symbols.append(definition.symbol_id)
                continue
            if (
                definition.has_trait(TRAIT_METRIC)
                and semantics.domain == "evaluation"
                and ("derived_metric" in config or "measurement" in config)
            ):
                if definition.implementation is not None:
                    raise ResearchImplementationResolutionError(
                        "declarative metric cannot also declare an implementation: "
                        f"symbol={definition.symbol_id}"
                    )
                if "derived_metric" in config and "measurement" in config:
                    raise ResearchImplementationResolutionError(
                        "metric symbol must choose derived_metric or measurement semantics"
                    )
                if "derived_metric" in config:
                    program, operations = compile_declarative_metric_program(definition)
                else:
                    program, operations = compile_declarative_study_measurement_program(
                        definition
                    )
                declarative_symbols.append(definition.symbol_id)
                executables.append(
                    ResearchExecutableGraphBinding(
                        definition.symbol_id,
                        program,
                        executable_unit_domain(program),
                        operations,
                    )
                )
                continue
            if (
                definition.has_trait(TRAIT_ANALYSIS)
                and semantics.domain == "analysis"
                and "analysis" in config
            ):
                if definition.implementation is not None:
                    raise ResearchImplementationResolutionError(
                        "declarative analysis cannot also declare an implementation: "
                        f"symbol={definition.symbol_id}"
                    )
                program, operations = compile_declarative_analysis_program(definition)
                declarative_symbols.append(definition.symbol_id)
                executables.append(
                    ResearchExecutableGraphBinding(
                        definition.symbol_id,
                        program,
                        executable_unit_domain(program),
                        operations,
                    )
                )
                continue
            if definition.implementation is None:
                metadata_traits = scientific_metadata_traits(definition)
                owner_traits = platform_binding_traits(definition)
                if metadata_traits:
                    if owner_traits:
                        raise ResearchImplementationResolutionError(
                            "scientific metadata symbol cannot also be platform-bound: "
                            f"symbol={definition.symbol_id}"
                        )
                    metadata_symbols.append(definition.symbol_id)
                    continue
                if not owner_traits:
                    raise ResearchImplementationResolutionError(
                        "platform-resolved executable symbol has no canonical owner trait: "
                        f"node={node.graph_node_id} symbol={definition.symbol_id}"
                    )
                for owner_trait_id in owner_traits:
                    if self._symbol_bindings is None:
                        requirements.append(
                            ResearchSymbolRequirement(definition, owner_trait_id)
                        )
                        continue
                    try:
                        binding = self._symbol_bindings.resolve(
                            definition,
                            owner_trait_id=owner_trait_id,
                        )
                    except ResearchSymbolBindingMissing:
                        requirements.append(
                            ResearchSymbolRequirement(definition, owner_trait_id)
                        )
                        continue
                    binding.validate_symbol(definition)
                    platform_bindings.append(binding)
                continue
            if is_implementation(definition.implementation, EXECUTABLE_UNIT_IMPLEMENTATION_TYPE):
                if semantics.mode == "experimentation":
                    raise ResearchImplementationResolutionError(
                        "native NoetriumUnit implementation cannot execute through "
                        f"Experimentation target: node={node.graph_node_id}"
                    )
                resolved_machine = self._resolve_unit_once(definition)
                implementations.append(resolved_machine)
                executables.append(
                    ResearchExecutableGraphBinding(
                        definition.symbol_id,
                        resolved_machine.program,
                        executable_unit_domain(resolved_machine.program),
                        resolved_machine.operations,
                    )
                )
                continue
            if is_implementation(definition.implementation, METHOD_IMPLEMENTATION_TYPE):
                resolved_method = self._resolve_method_once(definition)
                implementations.append(resolved_method)
                if semantics.mode == "experimentation":
                    continue
                if semantics.mode != "unit" or semantics.domain != "method":
                    raise ResearchImplementationResolutionError(
                        "ResearchMethod requires unit/domain=method or Experimentation "
                        f"target: node={node.graph_node_id}"
                    )
                executables.append(
                    ResearchExecutableGraphBinding(
                        definition.symbol_id,
                        resolved_method.method,
                        "method",
                        method_program_operations(resolved_method.method),
                    )
                )
                continue
            resolved = self._resolve_callable_once(definition)
            implementations.append(resolved)
            if semantics.mode == "experimentation":
                continue
            if definition.has_trait(TRAIT_METHOD):
                raise ResearchImplementationResolutionError(
                    "METHOD definitions must use method implementation Unit"
                )
            domain = semantics.domain
            if semantics.mode != "unit" or domain is None:
                raise ResearchImplementationResolutionError(
                    "research node has a paper implementation but no executable Unit domain: "
                    f"node={node.graph_node_id} traits={semantic_traits!r} "
                    f"definition={definition.symbol_id}"
                )
            executables.append(
                compile_callable_unit_definition(
                    definition,
                    domain=domain,
                    resolved=resolved,
                )
            )
        experiment_definition = None
        experiment_binding = None
        research_plan = None
        experiment_program = None
        if semantics.mode == "experimentation":
            if (
                graph_id is None
                or graph_digest is None
                or research_revision_digest is None
            ):
                raise ResearchExperimentCompilationMissing(
                    "Experimentation lowering requires complete NoetriumUnit identity"
                )
            if self._experiment_compilation is None:
                raise ResearchExperimentCompilationMissing(
                    "Experimentation lowering requires explicit Unit-native Experiment compiler"
                )
            compiled_experiment = self._experiment_compilation.resolve(node)
            if type(compiled_experiment) is not tuple or len(compiled_experiment) != 4:
                raise TypeError(
                    "Experiment compiler must return "
                    "(definition, binding, research_plan, experiment_program)"
                )
            (
                experiment_definition,
                experiment_binding,
                research_plan,
                experiment_program,
            ) = compiled_experiment

        return ResearchGraphExecutionBinding(
            graph_node_id=node.graph_node_id,
            semantic_traits=semantic_traits,
            lowering_mode=semantics.mode,
            domain=semantics.domain,
            source_semantic_digest=node.semantic_digest,
            symbol_ids=tuple(row.symbol_id for row in node.symbols),
            implementations=tuple(implementations),
            platform_bindings=tuple(platform_bindings),
            platform_requirements=tuple(requirements),
            declarative_symbol_ids=tuple(declarative_symbols),
            metadata_symbol_ids=tuple(metadata_symbols),
            executables=tuple(executables),
            experiment_definition=experiment_definition,
            experiment_binding=experiment_binding,
            research_plan=research_plan,
            experiment_program=experiment_program,
        )

    def compile(
        self,
        compilation: ResearchCompilationView,
        *,
        selected_node_ids: tuple[str, ...] | None = None,
    ) -> tuple[ResearchGraphExecutionBinding, ...]:
        if type(compilation) is not ResearchCompilationView:
            raise TypeError("research execution binding requires ResearchCompilationView")
        nodes: tuple[ResearchExecutionBinding, ...]
        if selected_node_ids is None:
            nodes = compilation.bindings
        else:
            if type(selected_node_ids) is not tuple or not selected_node_ids or any(
                type(node_id) is not str or not node_id.strip()
                for node_id in selected_node_ids
            ):
                raise TypeError("Research execution lowering selection must be a non-empty text tuple")
            selected = set(selected_node_ids)
            if len(selected) != len(selected_node_ids):
                raise ValueError("Research execution lowering selection node ids must be unique")
            unknown: list[str] = []
            for node_id in selected:
                try:
                    compilation.binding(node_id)
                except KeyError:
                    unknown.append(node_id)
            if unknown:
                raise ValueError(
                    "Research execution lowering selection references unknown nodes: "
                    f"{tuple(sorted(unknown))}"
                )
            nodes = tuple(
                compilation.binding(node_id)
                for node_id in sorted(selected)
            )
        return tuple(
            self.compile_node(
                node,
                graph_id=compilation.graph_id,
                graph_digest=compilation.graph_digest,
                research_revision_digest=compilation.research_revision_digest,
            )
            for node in nodes
        )


def compile_research_execution_bindings(
    compilation: ResearchCompilationView,
    *,
    resolver: ResearchImplementationResolverPort | None = None,
    experiment_compilation: ResearchExperimentCompilationPort | None = None,
    symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
    selected_node_ids: tuple[str, ...] | None = None,
) -> tuple[ResearchGraphExecutionBinding, ...]:
    return ResearchExecutionBindingCompiler(
        resolver,
        experiment_compilation,
        symbol_bindings,
    ).compile(
        compilation,
        selected_node_ids=selected_node_ids,
    )


__all__ = [
    "ImportResearchImplementationResolver",
    "ResearchExecutionBindingCompiler",
    "ResearchImplementationResolutionError",
    "ResearchImplementationResolverPort",
    "ResearchExecutableGraphBinding",
    "ResearchGraphExecutionBinding",
    "ResolvedResearchImplementation",
    "ResolvedExecutableUnitImplementation",
    "compile_callable_unit_definition",
    "compile_callable_method_definition",
    "compile_research_execution_bindings",
    "research_execution_bindings_digest",
    "resolve_executable_unit_implementation",
]
