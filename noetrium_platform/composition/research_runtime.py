from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit
from noetrium_platform.research.experimentation.scientific_evidence import (
    scientific_evidence_graph,
    scientific_evidence_payload,
)
from noetrium_platform.research.experimentation.api.research_compiler import research_plan_study, research_plan_protocol, research_plan_value, research_plan_digest, compile_research_participant_schedule
from noetrium_platform.research.experimentation.api.program import require_experiment_compilation, experiment_compilation_plan, experiment_compilation_batches, experiment_compilation_execution_graph, experiment_compilation_batch_digest
from noetrium_platform.research.experimentation.lifecycle.study.api.plan import (
    study_plan_protocol,
    study_plan_assignment_matrix,
    study_plan_digest,
    study_plan_binding_digest,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import study_protocol_digest
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import study_experiment_id

from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from enum import Enum
from threading import RLock

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskContextPort
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.shared_host_pressure import (
    ResourceCompetitionDemand,
    StorageCompetitionDemand,
)
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    ExecutionContext,
    JsonObject,
    JsonValue,
    MachineCut,
    MachineStatus,
    canonical_bytes,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.foundation.kernel.kernel.universal import executable_unit_required_capabilities

from noetrium_platform.research.execution.graph.api import (
    ResearchGraphReconciliationDisposition,
)
from noetrium_platform.research.experimentation.api import (
    ExperimentProgramBinding,
    experiment_report_from_data,
)
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.governance.api import (
    NoetriumUnit,
    ScopeKind,
    scope_to_data,
    scope_unit,
)
from .research_execution_content import ResearchExecutionContentAuthorities
from noetrium_platform.foundation.kernel.structure import GraphStorageKind
from noetrium_platform.foundation.kernel.structure import is_implementation
from noetrium_platform.product.research_implementation import (
    METHOD_IMPLEMENTATION_TYPE,
    resolve_method_implementation,
)
from noetrium_platform.research.execution.workflow.runtime import (
    execute_bound_method_program,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodObservationPort,
    OperationDispatchPort,
    MethodRunStatus,
    MethodRuntimeContext,
    MethodRuntimePortInventory,
    ProgramScopedCapabilityPort,
    plan_method_runtime_binding,
    method_runtime_binding_digest,
    require_complete_method_runtime_binding,
)
from .research_checkpoint import (
    ResearchCheckpointIndeterminate,
    ResearchNodeCheckpointProof,
)
from .research_experiment import (
    ResearchExperimentRuntimeBinding,
    ResearchExperimentRuntimeBindingPort,
    ResearchScientificInputBoundStudyExecutionPort,
    require_experiment_execution_binding,
)
from .research_execution import (
    ResearchNodeAdmission,
    ResearchNodeRuntimePort,
    ResearchPortfolioRuntimePort,
)
from noetrium_platform.foundation.kernel.unit_codec import unit_document
from .research_execution_graph import ResearchCompilationView, ResearchExecutionBinding
from .research_semantics import lowering_for_graph
from .research_unit_activation import (
    compose_research_node_method_runtime_inventory,
)
from .research_lowering import ResearchGraphExecutionBinding
from noetrium_platform.product.research_traits import TRAIT_PROGRAM
from .research_scientific_analysis import (
    materialize_research_scientific_inputs,
)
from .research_reconciliation import (
    ResearchNodeReconciliationProof,
    ResearchReconciliationIndeterminate,
)


def _scientific_json(value):
    """Project frozen scientific values without deepcopying immutable mappings."""
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, Enum):
        return value.value
    if type(value) is NoetriumUnit:
        return unit_document(value)
    if is_dataclass(value):
        return {
            item.name: _scientific_json(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _scientific_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_scientific_json(item) for item in value)
    raise TypeError(
        "scientific value is not JSON-projectable: " + type(value).__qualname__
    )


class CanonicalResearchRuntimeUnsupported(RuntimeError):
    pass


class CanonicalResearchRuntimeFailure(RuntimeError):
    def __init__(self, message: str, *, failure_id: str | None = None) -> None:
        self.failure_id = failure_id
        super().__init__(message)


def _machine_failure_cause(semantic_state: object) -> str:
    """Project only the lower Machine's committed failure provenance."""
    if not isinstance(semantic_state, Mapping):
        return ""
    lower = semantic_state.get("unit_failure")
    if not isinstance(lower, Mapping):
        return ""
    return (
        f" lower_failure_code={lower.get('code')!r}"
        f" lower_cursor={lower.get('cursor')!r}"
        f" lower_error_digest={lower.get('error_digest')!r}"
        f" lower_message={lower.get('message')!r}"
    )


class CanonicalResearchNodeRuntime(
    ResearchNodeRuntimePort,
    ResearchPortfolioRuntimePort,
):
    """Built-in strict runtime for already unambiguous Machine lowerings.

    Experiment-family nodes are intentionally rejected until their top-level
    semantics lower to the existing ExperimentProgram/Trial authorities.
    """

    def __init__(
        self,
        state_root: str | Path,
        *,
        execution_pool: ResearchExecutionPool | None = None,
        experiment_bindings: ResearchExperimentRuntimeBindingPort | None = None,
        method_runtime_inventory: MethodRuntimePortInventory | None = None,
        operation_dispatcher: OperationDispatchPort | None = None,
        method_observation: MethodObservationPort | None = None,
        content_authorities: ResearchExecutionContentAuthorities,
        max_steps: int | None = None,
    ) -> None:
        if not isinstance(state_root, (str, Path)):
            raise TypeError("canonical Research execution runtime state_root is required")
        root = Path(state_root).absolute()
        if root.exists() and not root.is_dir():
            raise ValueError("canonical Research execution runtime state_root must be a directory")
        if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
            raise ValueError("canonical Research execution runtime max_steps must be positive or None")
        if (execution_pool is None) != (experiment_bindings is None):
            raise ValueError(
                "canonical Experiment runtime requires both execution_pool and "
                "experiment_bindings"
            )
        if execution_pool is not None and type(execution_pool) is not ResearchExecutionPool:
            raise TypeError(
                "canonical Experiment runtime execution_pool must be ResearchExecutionPool"
            )
        if experiment_bindings is not None and not isinstance(
            experiment_bindings,
            ResearchExperimentRuntimeBindingPort,
        ):
            raise TypeError(
                "canonical Experiment runtime binding resolver must satisfy "
                "ResearchExperimentRuntimeBindingPort"
            )
        if method_runtime_inventory is not None and not isinstance(
            method_runtime_inventory,
            MethodRuntimePortInventory,
        ):
            raise TypeError(
                "canonical Method runtime inventory must be MethodRuntimePortInventory"
            )
        if type(content_authorities) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "canonical Research execution runtime requires ResearchExecutionContentAuthorities"
            )
        root.mkdir(parents=True, exist_ok=True)
        self._state_root = root
        self._execution_pool = execution_pool
        self._experiment_bindings = experiment_bindings
        self._method_runtime_inventory = (
            MethodRuntimePortInventory()
            if method_runtime_inventory is None
            else method_runtime_inventory
        )
        self._max_steps = max_steps
        self._operation_dispatcher = operation_dispatcher
        self._method_observation = method_observation
        self._content = content_authorities
        self._machine_journal = DirectoryMachineJournal(root / "unit-journal")
        self._node_method_runtime_inventories: dict[
            tuple[str, str],
            MethodRuntimePortInventory,
        ] = {}
        self._method_runtime_binding_plans: dict[
            tuple[str, str],
                ] = {}
        self._method_inventory_lock = RLock()

    def bind_portfolio(self, compilation: ResearchCompilationView) -> None:
        if type(compilation) is not ResearchCompilationView:
            raise TypeError(
                "canonical Research execution portfolio binding requires compiled graph"
            )
        staged: dict[tuple[str, str], MethodRuntimePortInventory] = {}

        # Resolve Program ownership from one immutable path index.  Rewalking the
        # recursive Unit tree per node is superlinear in large portfolios even
        # though every binding already carries its canonical path.
        program_scope_by_prefix = {
            path: "::".join(path)
            for path, _program in compilation.portfolio.paths_with_schema(
                TRAIT_PROGRAM
            )
        }
        program_scope_by_path: dict[tuple[str, ...], str | None] = {}
        scoped_base_by_scope: dict[str | None, MethodRuntimePortInventory] = {
            None: self._method_runtime_inventory
        }
        inventory_by_closure: dict[
            tuple[str | None, tuple[str, ...], tuple[str, ...]],
            MethodRuntimePortInventory,
        ] = {}

        def program_scope_for(path: tuple[str, ...]) -> str | None:
            cached = program_scope_by_path.get(path)
            if path in program_scope_by_path:
                return cached
            scope_id = None
            for length in range(len(path), 0, -1):
                candidate = program_scope_by_prefix.get(path[:length])
                if candidate is not None:
                    scope_id = candidate
                    break
            program_scope_by_path[path] = scope_id
            return scope_id

        # One immutable Method implementation can be referenced by many research
        # nodes in the same portfolio. Resolving it is pure but expensive because
        # it reconstructs and validates the canonical Method Unit. Pay that cost
        # once per exact implementation Unit, then project its digest in O(1).
        method_digest_by_implementation: dict[str, str] = {}

        def resolved_method_digest(definition: NoetriumUnit) -> str | None:
            implementation = definition.implementation
            if not is_implementation(
                implementation,
                METHOD_IMPLEMENTATION_TYPE,
            ):
                return None
            key = implementation.unit_digest
            cached = method_digest_by_implementation.get(key)
            if cached is not None:
                return cached
            digest = resolve_method_implementation(implementation).unit_digest
            existing = method_digest_by_implementation.setdefault(key, digest)
            if existing != digest:
                raise RuntimeError(
                    "immutable Method implementation resolved to multiple Unit identities"
                )
            return existing

        for node in compilation.bindings:
            # Only native Method Units consume node-scoped Method runtime
            # inventories. Experimentation owns its Method runtime through the
            # Trial binding authority; composing inventories here for those
            # nodes is redundant eager work and violates cheap-before-expensive
            # lowering.
            semantics = lowering_for_graph(node.graph)
            if semantics.mode != "unit" or semantics.domain != "method":
                continue

            method_graph_digests = tuple(
                digest
                for definition in node.symbols
                if (digest := resolved_method_digest(definition)) is not None
            )
            selected = (
                method_graph_digests
                if len(method_graph_digests) <= 1
                else ()
            )

            inventory_base = self._method_runtime_inventory
            scope_id: str | None = None
            capabilities = inventory_base.capabilities
            if isinstance(capabilities, ProgramScopedCapabilityPort):
                scope_id = program_scope_for(node.ref.path)
                inventory_base = scoped_base_by_scope.get(scope_id)
                if inventory_base is None:
                    inventory_base = self._method_runtime_inventory.for_program_scope(
                        scope_id
                    )
                    scoped_base_by_scope[scope_id] = inventory_base

            symbol_closure = tuple(
                definition.symbol_digest for definition in node.symbols
            )
            inventory_key = (scope_id, symbol_closure, selected)
            inventory = inventory_by_closure.get(inventory_key)
            if inventory is None:
                inventory = compose_research_node_method_runtime_inventory(
                    node.symbols,
                    inventory_base,
                    method_graph_digests=selected,
                    journal=self._machine_journal,
                    max_steps=self._max_steps,
                )
                inventory_by_closure[inventory_key] = inventory
            staged[(node.graph_node_id, node.semantic_digest)] = inventory

        with self._method_inventory_lock:
            for key, inventory in staged.items():
                current = self._node_method_runtime_inventories.get(key)
                if (
                    current is not None
                    and current.identity_digest != inventory.identity_digest
                ):
                    raise ValueError(
                        "node-scoped Method runtime inventory identity drifted: "
                        f"node_id={key[0]!r} semantic_digest={key[1]}"
                    )
            self._node_method_runtime_inventories.update(staged)

    def _method_inventory_for(
        self,
        node: ResearchExecutionBinding,
    ) -> MethodRuntimePortInventory:
        key = (node.graph_node_id, node.semantic_digest)
        with self._method_inventory_lock:
            return self._node_method_runtime_inventories.get(
                key,
                self._method_runtime_inventory,
            )

    def _method_binding_plan_for(
        self,
        program,
        inventory: MethodRuntimePortInventory,
    ) -> NoetriumUnit:
        key = (program.unit_digest, inventory.identity_digest)
        with self._method_inventory_lock:
            cached = self._method_runtime_binding_plans.get(key)
            if cached is not None:
                return cached
            plan = plan_method_runtime_binding(program, inventory)
            current = self._method_runtime_binding_plans.get(key)
            if current is not None:
                if method_runtime_binding_digest(current) != method_runtime_binding_digest(plan):
                    raise RuntimeError(
                        "Method runtime binding plan identity drifted for immutable inputs"
                    )
                return current
            self._method_runtime_binding_plans[key] = plan
            return plan

    @staticmethod
    def _experiment_admission_binding_digest(
        binding: ResearchGraphExecutionBinding,
        runtime_binding: ResearchExperimentRuntimeBinding,
    ) -> str:
        execution = require_experiment_execution_binding(binding)
        runtime_binding.validate_execution_binding(execution)
        return canonical_digest(
            {
                "runtime": "canonical-research-experiment-runtime",
                "version": 1,
                "execution_binding_digest": execution.binding_digest,
                "runtime_binding_digest": runtime_binding.runtime_binding_digest,
                "experiment_program_digest": (
                    experiment_compilation_execution_graph(execution.experiment_program).unit_digest
                ),
                "experiment_batch_plan_digest": (
                    experiment_compilation_batch_digest(execution.experiment_program)
                ),
                "platform_symbol_bindings": tuple(
                    row.binding_digest for row in binding.platform_bindings
                ),
                "journal": "directory-machine-journal",
            }
        )

    def admit(
        self,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
    ) -> ResearchNodeAdmission:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("canonical Research execution runtime requires compiled node")
        if type(binding) is not ResearchGraphExecutionBinding:
            raise TypeError("canonical Research execution runtime requires lowered node")
        binding.validate_source(node)
        if binding.lowering_mode == "experimentation":
            execution = require_experiment_execution_binding(binding)
            if node.graph.boundary.outputs and (
                len(node.graph.boundary.outputs) != 1
                or node.graph.boundary.outputs[0].type_ref.storage_kind is not GraphStorageKind.ARTIFACT
            ):
                raise CanonicalResearchRuntimeUnsupported(
                    "Experimentation may expose only one ARTIFACT report output"
                )
            if self._execution_pool is None or self._experiment_bindings is None:
                raise CanonicalResearchRuntimeUnsupported(
                    "canonical Experiment execution requires exact runtime binding "
                    "and explicit ResearchExecutionPool"
                )
            runtime_binding = self._experiment_bindings.resolve(execution)
            if type(runtime_binding) is not ResearchExperimentRuntimeBinding:
                raise TypeError(
                    "experiment runtime binding resolver returned invalid binding"
                )
            binding_digest = self._experiment_admission_binding_digest(
                binding,
                runtime_binding,
            )
            return ResearchNodeAdmission(
                node.graph_node_id,
                node.semantic_digest,
                binding.binding_digest,
                binding_digest,
            )

        if binding.platform_requirements:
            raise CanonicalResearchRuntimeUnsupported(
                "canonical Research execution runtime received unresolved platform requirements: "
                f"node={node.graph_node_id} requirements="
                f"{tuple(row.symbol_id for row in binding.platform_requirements)}"
            )

        if binding.lowering_mode == "unit":
            if len(binding.executables) != 1:
                raise CanonicalResearchRuntimeUnsupported(
                    "executable research node must lower to exactly one NoetriumUnit: "
                    f"node={node.graph_node_id!r} "
                    f"traits={binding.semantic_traits!r} "
                    f"executable_count={len(binding.executables)} "
                    f"executable_ids={tuple(row.symbol_id for row in binding.executables)!r}"
                )
            executable = binding.executables[0]
            dependency: dict[str, object] = {
                "runtime": "canonical-research-unit-runtime",
                "version": 3,
                "semantic_traits": binding.semantic_traits,
                "lowering_mode": "unit",
                "domain": executable.domain,
                "unit_digest": executable.graph.unit_digest,
                "operations_digest": executable.operations_digest,
                "platform_symbol_bindings": tuple(
                    row.binding_digest for row in binding.platform_bindings
                ),
                "journal": "directory-unit-journal",
                "max_steps": self._max_steps,
            }
            if executable.domain == "method":
                inventory = self._method_inventory_for(node)
                binding_plan = self._method_binding_plan_for(
                    executable.graph,
                    inventory,
                )
                try:
                    require_complete_method_runtime_binding(binding_plan)
                except RuntimeError as exc:
                    raise CanonicalResearchRuntimeUnsupported(
                        "Method Unit runtime binding is incomplete: "
                        f"node={node.graph_node_id} details={exc}"
                    ) from exc
                dependency.update({
                    "method_runtime_inventory_digest": inventory.identity_digest,
                    "method_runtime_binding_plan_digest": (
                        method_runtime_binding_digest(binding_plan)
                    ),
                })
            elif executable_unit_required_capabilities(executable.graph):
                raise CanonicalResearchRuntimeUnsupported(
                    "executable Unit declares external capabilities but has no "
                    "generic capability runtime binding"
                )
            binding_digest = canonical_digest(dependency)
            return ResearchNodeAdmission(
                node.graph_node_id,
                node.semantic_digest,
                binding.binding_digest,
                binding_digest,
            )

        raise CanonicalResearchRuntimeUnsupported(
            "Research execution node target has no canonical built-in runtime yet: "
            f"node={node.graph_node_id} traits={binding.semantic_traits!r}"
        )

    def execute(
        self,
        context: ExecutionContext,
        task_context: TaskContextPort,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
        inputs: JsonObject,
        *,
        execution_cut_id: str,
        deadline: Deadline | None,
    ) -> JsonValue:
        if not isinstance(context, ExecutionContext):
            raise TypeError("canonical Research execution runtime requires ExecutionContext")
        task_context.checkpoint()
        if type(inputs) is not dict:
            raise TypeError("canonical Research execution runtime inputs must be JsonObject")
        require_sha256(execution_cut_id, "canonical Research execution execution_cut_id")
        if deadline is not None and deadline.expired:
            raise CanonicalResearchRuntimeFailure(
                "canonical Research execution node deadline expired before execution"
            )

        admission = self.admit(node, binding)
        runtime_context = replace(
            context,
            component_id=node.graph_node_id,
        )
        payload: JsonValue = inputs if inputs else None
        # Research edges carry typed scientific artifacts. Their actual type,
        # not an optional downstream "analysis_engine" implementation flag,
        # determines whether authoritative report references are materialized.
        # Other executable Unit inputs retain their original identity.
        if binding.lowering_mode == "unit":
            payload = materialize_research_scientific_inputs(
                payload,
                self._content,
            )
        machine_id = self._machine_id(
            context.run_id,
            node.graph_node_id,
            binding.binding_digest,
        )

        if binding.lowering_mode == "experimentation":
            return self._execute_experiment(
                machine_id,
                binding,
                admission.runtime_binding_digest,
                scientific_inputs=inputs,
                execution_cut_id=execution_cut_id,
                execution_context=context,
                execution_control=task_context,
                has_outputs=bool(node.graph.boundary.outputs),
                deadline=deadline,
            )
        if binding.lowering_mode == "unit":
            return self._execute_unit(
                runtime_context,
                machine_id,
                node,
                binding,
                payload,
                admission.runtime_binding_digest,
            )
        raise CanonicalResearchRuntimeUnsupported(
            "canonical runtime execution target was not admitted"
        )

    def _artifact_reference_json(
        self,
        reference: ArtifactReference,
    ) -> JsonObject:
        if type(reference) is not ArtifactReference:
            raise TypeError("Experiment report requires ArtifactReference")
        record = self._content.artifacts.get(reference.artifact_id)
        return {
            "reference_id": reference.reference_id,
            "scope": scope_to_data(reference.scope),
            "artifact_id": reference.artifact_id,
            "generation": reference.generation,
            "content_sha256": record.digest,
            "media_type": record.media_type,
            "artifact_kind": record.kind.value,
            "retention": record.retention.value,
        }

    def _publish_exact_json(
        self,
        *,
        execution_cut_id: str,
        reference_id: str,
        payload: JsonValue,
        kind: ArtifactKind,
        metadata: Mapping[str, str],
    ) -> ArtifactReference:
        require_sha256(execution_cut_id, "Experiment Artifact execution cut")
        body = canonical_bytes(payload, indent=2) + b"\n"
        reference = self._content.publish(
            reference_id=reference_id,
            scope=scope_unit(ScopeKind.EXECUTION_CUT, execution_cut_id),
            payload=body,
            media_type="application/json",
            kind=kind,
            retention=ArtifactRetention.PROJECT,
            producer_component_id="research.experiment-report",
            metadata=metadata,
        )
        if self._content.read(reference) != body:
            raise CanonicalResearchRuntimeFailure(
                "canonical Artifact authority returned content drift"
            )
        return reference

    def _publish_experiment_report(
        self,
        binding: ResearchGraphExecutionBinding,
        runtime_binding: ResearchExperimentRuntimeBinding,
        report,
        *,
        execution_cut_id: str,
    ) -> JsonObject:
        execution = require_experiment_execution_binding(binding)
        runtime_binding.validate_execution_binding(execution)
        prefix = f"experiment:{execution.binding_digest}"
        base_metadata = {
            "execution_binding_digest": execution.binding_digest,
            "execution_cut_id": execution_cut_id,
            "research_plan_digest": research_plan_digest(execution.research_plan),
        }
        protocol = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:protocol",
            payload={
                "protocol": _scientific_json(
                    study_plan_protocol(
                        experiment_compilation_plan(execution.experiment_program)
                    )
                ),
                "assignment_matrix": _scientific_json(
                    study_plan_assignment_matrix(
                        experiment_compilation_plan(execution.experiment_program)
                    )
                ),
            },
            kind=ArtifactKind.SCIENTIFIC,
            metadata={**base_metadata, "report_part": "protocol"},
        )
        observations = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:observations",
            payload=tuple(_scientific_json(row) for row in report.observations),
            kind=ArtifactKind.REPORT,
            metadata={**base_metadata, "report_part": "observations"},
        )
        aggregates = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:aggregates",
            payload=tuple(_scientific_json(row) for row in report.aggregates),
            kind=ArtifactKind.REPORT,
            metadata={**base_metadata, "report_part": "aggregates"},
        )
        evidence_graph = scientific_evidence_graph(report)
        evidence_graph_ref = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:scientific-evidence-graph",
            payload=scientific_evidence_payload(evidence_graph),
            kind=ArtifactKind.SCIENTIFIC,
            metadata={**base_metadata, "report_part": "scientific_evidence_graph"},
        )
        manifest_payload: JsonObject = {
            "schema": "research.experiment-report-manifest.v4",
            "execution_binding_digest": execution.binding_digest,
            "execution_cut_id": execution_cut_id,
            "content_authority_digest": self._content.identity_digest,
            "research_plan_digest": research_plan_digest(execution.research_plan),
            "experiment_program_digest": (
                experiment_compilation_execution_graph(execution.experiment_program).unit_digest
            ),
            "protocol_digest": report.protocol_digest,
            "binding_digest": report.binding_digest,
            "plan_digest": report.plan_digest,
            "observation_count": len(report.observations),
            "aggregate_count": len(report.aggregates),
            "protocol_artifact": self._artifact_reference_json(protocol),
            "observations_artifact": self._artifact_reference_json(observations),
            "aggregates_artifact": self._artifact_reference_json(aggregates),
            "scientific_evidence_graph_artifact": self._artifact_reference_json(evidence_graph_ref),
            "scientific_evidence_graph_digest": evidence_graph.semantic_digest,
        }
        manifest = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:report-manifest",
            payload=manifest_payload,
            kind=ArtifactKind.REPORT,
            metadata={**base_metadata, "report_part": "manifest"},
        )
        return {
            "schema": "research.experiment-report-ref.v4",
            "execution_binding_digest": execution.binding_digest,
            "execution_cut_id": execution_cut_id,
            "content_authority_digest": self._content.identity_digest,
            "manifest": self._artifact_reference_json(manifest),
        }

    def _execute_experiment(
        self,
        machine_id: str,
        binding: ResearchGraphExecutionBinding,
        admission_binding_digest: str,
        *,
        scientific_inputs: JsonObject,
        execution_cut_id: str,
        execution_context: ExecutionContext,
        execution_control: TaskContextPort,
        has_outputs: bool,
        deadline: Deadline | None,
    ) -> JsonValue:
        execution = require_experiment_execution_binding(binding)
        if self._execution_pool is None or self._experiment_bindings is None:
            raise CanonicalResearchRuntimeUnsupported(
                "Experimentation execution is not explicitly bound"
            )
        runtime_binding = self._experiment_bindings.resolve(execution)
        if type(runtime_binding) is not ResearchExperimentRuntimeBinding:
            raise TypeError(
                "experiment runtime binding resolver returned invalid binding"
            )
        observed_admission = self._experiment_admission_binding_digest(
            binding,
            runtime_binding,
        )
        if observed_admission != admission_binding_digest:
            raise CanonicalResearchRuntimeFailure(
                "Experiment runtime binding drifted after admission"
            )

        group = self._execution_pool.open_experiment_group(
            f"research-experiment:{canonical_digest({'machine_id': machine_id})}",
            tenant_id=execution_context.execution_tenant_id,
            resource_id=(
                "research-experiment:"
                f"{study_experiment_id(execution.experiment_definition)}"
            ),
            resource_demand=(
                ResourceCompetitionDemand(
                    storage_targets=(
                        StorageCompetitionDemand(self._state_root),
                    ),
                )
                if self._execution_pool.resource_competition_enabled
                else None
            ),
            deadline=deadline,
        )
        adapter = runtime_binding.adapter
        if scientific_inputs:
            if not isinstance(
                adapter,
                ResearchScientificInputBoundStudyExecutionPort,
            ):
                raise CanonicalResearchRuntimeUnsupported(
                    "Experiment received upstream scientific inputs but its "
                    "Study execution adapter cannot bind them"
                )
            adapter = adapter.bind_scientific_inputs(scientific_inputs)

        completed = False
        try:
            report = ExperimentProgramBinding(
                execution.experiment_program,
                adapter,
                execution_binding_digest=runtime_binding.runtime_binding_digest,
                execution_context=execution_context,
                execution_control=execution_control,
                task_group=group,
            ).execute(
                journal=self._machine_journal,
                machine_id=machine_id,
            )
            if (
                report.protocol_digest
                != study_protocol_digest(study_plan_protocol(experiment_compilation_plan(execution.experiment_program)))
                or report.binding_digest
                != study_plan_binding_digest(experiment_compilation_plan(execution.experiment_program))
                or report.plan_digest
                != study_plan_digest(experiment_compilation_plan(execution.experiment_program))
            ):
                raise CanonicalResearchRuntimeFailure(
                    "Experiment report identity drifted from admitted execution"
                )
            report_ref = self._publish_experiment_report(
                binding,
                runtime_binding,
                report,
                execution_cut_id=execution_cut_id,
            )
            completed = True
            return report_ref if has_outputs else None
        finally:
            self._execution_pool.close_experiment_group(
                group,
                cancel_pending=not completed,
                deadline=deadline,
            )


    def _require_operation_dispatcher(self) -> OperationDispatchPort:
        dispatcher = self._operation_dispatcher
        if dispatcher is None:
            raise CanonicalResearchRuntimeUnsupported(
                "Method execution requires the managed durable Operation authority"
            )
        return dispatcher

    def _execute_unit(
        self,
        context: ExecutionContext,
        machine_id: str,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
        payload: JsonValue,
        runtime_binding_digest: str,
    ) -> JsonValue:
        executable = binding.executables[0]
        host = BoundExecutableUnit(
            host_id=f"research:unit:{executable.symbol_id}",
            unit=executable.graph,
            operations=executable.operations,
            journal=self._machine_journal,
            max_steps=self._max_steps,
            dependency_identity={
                "runtime_binding_digest": runtime_binding_digest,
                "execution_cut_id": context.run_id,
                "graph_node_id": binding.graph_node_id,
                "unit_digest": executable.graph.unit_digest,
                "domain": executable.domain,
            },
        )

        if executable.domain == "method":
            inventory = self._method_inventory_for(node)
            binding_plan = self._method_binding_plan_for(
                executable.graph,
                inventory,
            )
            require_complete_method_runtime_binding(binding_plan)
            runtime = MethodRuntimeContext(
                context,
                capabilities=inventory.capabilities,
                agent_loop=inventory.agent_loop,
                schemas=inventory.schemas,
                unit_activation=inventory.unit_activation,
                dispatcher=self._require_operation_dispatcher(),
                observation=self._method_observation,
                binding_plan_digest=method_runtime_binding_digest(binding_plan),
                runtime_binding_digest=runtime_binding_digest,
                program_binding=host,
                machine_id=machine_id,
            )
            result = execute_bound_method_program(
                executable.graph,
                runtime=runtime,
                input_value=payload,
            )
            if result.status is not MethodRunStatus.SUCCEEDED:
                raise CanonicalResearchRuntimeFailure(
                    "executable Method Unit did not reach SUCCEEDED: "
                    f"status={result.status.value} "
                    f"failure_code={result.failure_code!r} "
                    f"failure={result.failure!r}",
                    failure_id=result.failure_id,
                )
            return result.value

        result = host.execute(
            machine_id=machine_id,
            instance_identity={
                "execution_cut_id": context.run_id,
                "graph_node_id": binding.graph_node_id,
                "semantic_digest": binding.source_semantic_digest,
                "binding_digest": binding.binding_digest,
                "runtime_binding_digest": runtime_binding_digest,
                "unit_digest": executable.graph.unit_digest,
                "domain": executable.domain,
            },
            binding=None,
            initial_data={},
            payload=payload,
            command_id_prefix=machine_id,
        )
        if result.status is not MachineStatus.COMPLETED:
            # Never collapse the one durable Machine Journal's committed
            # failure to an opaque status=failed.
            cause = _machine_failure_cause(result.semantic_state)
            raise CanonicalResearchRuntimeFailure(
                "executable Unit did not reach COMPLETED: "
                f"domain={executable.domain!r} status={result.status.value}"
                + cause
            )
        return result.previous_value

    def checkpoint_node(
        self,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
        *,
        execution_cut_id: str,
        attempt_id: str,
    ) -> ResearchNodeCheckpointProof:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("canonical checkpoint requires compiled graph node")
        if type(binding) is not ResearchGraphExecutionBinding:
            raise TypeError("canonical checkpoint requires lowered graph node")
        binding.validate_source(node)
        require_sha256(execution_cut_id, "canonical checkpoint execution_cut_id")
        execution_attempt_id = self._execution_attempt_id(
            execution_cut_id,
            node.graph_node_id,
            attempt_id,
        )
        machine_id = self._machine_id(
            execution_attempt_id,
            node.graph_node_id,
            binding.binding_digest,
        )
        journal = self._machine_journal
        head = journal.latest(machine_id)
        if head is None:
            raise ResearchCheckpointIndeterminate(
                "lower Machine has no accepted journal head"
            )
        expected_program_digest = self._lower_program_digest(binding)
        if head.unit_digest != expected_program_digest:
            raise CanonicalResearchRuntimeFailure(
                "lower Machine journal program identity drifted during checkpoint"
            )
        if head.accepted_status not in {
            MachineStatus.COMPLETED,
            MachineStatus.FAILED,
            MachineStatus.WAITING,
            MachineStatus.INTERRUPTED,
        }:
            raise ResearchCheckpointIndeterminate(
                "lower Machine head is not at a checkpoint-safe status: "
                f"{head.accepted_status.value}"
            )
        cut = MachineCut.from_commit(head)
        return ResearchNodeCheckpointProof(
            execution_cut_id,
            node.graph_node_id,
            node.semantic_digest,
            binding.binding_digest,
            "machine-journal",
            cut,
            (head.commit_id,),
        )

    def reconcile_node(
        self,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
        *,
        execution_cut_id: str,
        attempt_id: str,
    ) -> ResearchNodeReconciliationProof:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("canonical reconciliation requires compiled graph node")
        if type(binding) is not ResearchGraphExecutionBinding:
            raise TypeError("canonical reconciliation requires lowered graph node")
        binding.validate_source(node)
        require_sha256(execution_cut_id, "canonical reconciliation execution_cut_id")
        if type(attempt_id) is not str or not attempt_id.strip():
            raise ValueError("canonical reconciliation attempt_id is required")

        execution_attempt_id = self._execution_attempt_id(
            execution_cut_id,
            node.graph_node_id,
            attempt_id,
        )
        machine_id = self._machine_id(
            execution_attempt_id,
            node.graph_node_id,
            binding.binding_digest,
        )
        journal = self._machine_journal
        head = journal.latest(machine_id)
        expected_program_digest = self._lower_program_digest(binding)
        if head is not None:
            if head.unit_digest != expected_program_digest:
                raise CanonicalResearchRuntimeFailure(
                    "lower Machine journal program identity drifted during reconciliation"
                )
            if head.accepted_status is MachineStatus.COMPLETED:
                result = self._recovered_result(
                    node,
                    binding,
                    head.state,
                    execution_cut_id=execution_cut_id,
                )
                return ResearchNodeReconciliationProof(
                    execution_cut_id,
                    node.graph_node_id,
                    node.semantic_digest,
                    binding.binding_digest,
                    attempt_id,
                    ResearchGraphReconciliationDisposition.SUCCEEDED,
                    "machine-journal",
                    (head.commit_id,),
                    result=result,
                )
            if head.accepted_status is MachineStatus.FAILED:
                return ResearchNodeReconciliationProof(
                    execution_cut_id,
                    node.graph_node_id,
                    node.semantic_digest,
                    binding.binding_digest,
                    attempt_id,
                    ResearchGraphReconciliationDisposition.FAILED,
                    "machine-journal",
                    (head.commit_id,),
                    failure_type="LowerMachineFailed",
                    failure_message=(
                        "lower Machine committed FAILED at "
                        f"revision={head.revision} commit={head.commit_id}"
                    ),
                )

        if binding.lowering_mode == "experimentation":
            graph_binding = binding
            execution = require_experiment_execution_binding(graph_binding)
            if self._experiment_bindings is None:
                raise CanonicalResearchRuntimeUnsupported(
                    "Experiment reconciliation requires exact runtime binding authority"
                )
            experiment_binding = self._experiment_bindings.resolve(execution)
            if type(experiment_binding) is not ResearchExperimentRuntimeBinding:
                raise TypeError(
                    "experiment reconciliation resolver returned invalid binding"
                )
            experiment_binding.validate_execution_binding(execution)
            proof = experiment_binding.reconciliation.reconcile(
                execution,
                machine_id=machine_id,
                execution_cut_id=execution_cut_id,
                graph_node_id=node.graph_node_id,
                semantic_digest=node.semantic_digest,
                binding_digest=graph_binding.binding_digest,
                attempt_id=attempt_id,
            )
            if type(proof) is not ResearchNodeReconciliationProof:
                raise TypeError(
                    "experiment reconciliation authority returned invalid proof"
                )
            proof.validate(
                node,
                graph_binding,
                execution_cut_id=execution_cut_id,
                attempt_id=attempt_id,
            )
            return proof

        raise ResearchReconciliationIndeterminate(
            "lower Machine has no terminal commit proving a safe graph disposition"
        )

    def _lower_program_digest(
        self,
        binding: ResearchGraphExecutionBinding,
    ) -> str:
        if binding.lowering_mode == "experimentation":
            execution = require_experiment_execution_binding(binding)
            return experiment_compilation_execution_graph(
                execution.experiment_program
            ).unit_digest
        if binding.lowering_mode == "unit":
            return binding.executables[0].graph.unit_digest
        raise CanonicalResearchRuntimeUnsupported(
            "reconciliation target has no executable Unit"
        )

    def _recovered_result(
        self,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
        machine_state: JsonObject,
        *,
        execution_cut_id: str,
    ) -> JsonValue:
        program_state = machine_state.get("_unit")
        if not isinstance(program_state, Mapping):
            raise CanonicalResearchRuntimeFailure(
                "completed lower Machine lost canonical NoetriumUnit state"
            )
        if binding.lowering_mode == "experimentation":
            execution = require_experiment_execution_binding(binding)
            if self._experiment_bindings is None:
                raise CanonicalResearchRuntimeUnsupported(
                    "Experiment execution requires exact runtime binding authority"
                )
            data = program_state.get("data")
            report = experiment_report_from_data(
                execution.experiment_program,
                data,
            )
            binding = self._experiment_bindings.resolve(execution)
            if type(binding) is not ResearchExperimentRuntimeBinding:
                raise TypeError(
                    "experiment recovery resolver returned invalid binding"
                )
            binding.validate_execution_binding(execution)
            report_ref = self._publish_experiment_report(
                binding,
                binding,
                report,
                execution_cut_id=execution_cut_id,
            )
            return report_ref if node.graph.boundary.outputs else None
        return program_state.get("previous_value")


    @staticmethod
    def _execution_attempt_id(
        execution_cut_id: str,
        graph_node_id: str,
        attempt_id: str,
    ) -> str:
        require_sha256(execution_cut_id, "Research execution execution cut identity")
        if type(graph_node_id) is not str or not graph_node_id.strip():
            raise ValueError("Research execution graph_node_id is required")
        if type(attempt_id) is not str or not attempt_id.strip():
            raise ValueError("Research execution attempt_id is required")
        return canonical_digest(
            {
                "schema": "noetrium.research-node-attempt.v1",
                "execution_cut_id": execution_cut_id,
                "graph_node_id": graph_node_id,
                "attempt_id": attempt_id,
            }
        )

    @staticmethod
    def _machine_id(
        execution_attempt_id: str,
        graph_node_id: str,
        binding_digest: str,
    ) -> str:
        """Return the stable lower-Machine identity for one durable graph attempt.

        binding_digest is validated by admission/program identity, but is deliberately
        excluded from Machine identity. Reconciliation must address the same durable
        attempt after a control-plane/code restart even when a new binding implementation
        would produce a different digest.
        """
        require_sha256(
            execution_attempt_id,
            "Research execution execution attempt identity",
        )
        if type(graph_node_id) is not str or not graph_node_id.strip():
            raise ValueError("Research execution graph_node_id is required")
        require_sha256(binding_digest, "Research execution binding digest")
        identity = canonical_digest(
            {
                "schema": "noetrium.research-machine-identity.v2",
                "execution_attempt_id": execution_attempt_id,
                "graph_node_id": graph_node_id,
            }
        )
        return f"research:{identity}"


__all__ = [
    "CanonicalResearchNodeRuntime",
    "CanonicalResearchRuntimeFailure",
    "CanonicalResearchRuntimeUnsupported",
]
