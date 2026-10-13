from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import JsonObject, canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    ResearchRequirementResolution,
    require_research_plan,
    research_plan_study,
    research_plan_value,
)
from noetrium_platform.research.experimentation.api.program import (
    experiment_compilation_plan,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BoundStudyExecutionPort,
    study_plan_digest,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_study_unit,
    study_definition_digest,
)
from noetrium_platform.composition.shared_host_pressure import ResourceCompetitionDemand
from noetrium_platform.composition.research_execution_graph import ResearchExecutionBinding
from noetrium_platform.composition.research_reconciliation import ResearchNodeReconciliationProof


class ResearchExperimentCompilationMissing(RuntimeError):
    pass


@runtime_checkable
class ResearchExperimentCompilationPort(Protocol):
    """Compile one Experimentation graph node into Unit-native execution inputs."""

    def resolve(
        self,
        node: ResearchExecutionBinding,
    ) -> tuple[
        NoetriumUnit,
        ResearchBindingContribution,
        NoetriumUnit,
        NoetriumUnit,
    ]: ...


@runtime_checkable
class ResearchExperimentExecutionBindingView(Protocol):
    """Derived Experiment fields exposed by one Research graph execution binding."""

    graph_node_id: str
    binding_digest: str
    experiment_definition: NoetriumUnit | None
    experiment_binding: ResearchBindingContribution | None
    research_plan: NoetriumUnit | None
    experiment_program: NoetriumUnit | None


_VALIDATED_EXPERIMENT_EXECUTION_BINDINGS: dict[str, None] = {}
_VALIDATED_EXPERIMENT_EXECUTION_BINDINGS_LOCK = RLock()
_VALIDATED_EXPERIMENT_EXECUTION_BINDINGS_LIMIT = 262144


def require_experiment_execution_binding(
    value: object,
) -> ResearchExperimentExecutionBindingView:
    if not isinstance(value, ResearchExperimentExecutionBindingView):
        raise TypeError("Experiment runtime requires Research execution binding")
    binding_digest = require_sha256(
        value.binding_digest,
        "Experiment execution binding digest",
    )
    with _VALIDATED_EXPERIMENT_EXECUTION_BINDINGS_LOCK:
        if binding_digest in _VALIDATED_EXPERIMENT_EXECUTION_BINDINGS:
            return value
    definition = value.experiment_definition
    contribution = value.experiment_binding
    plan = value.research_plan
    program = value.experiment_program
    if (
        definition is None
        or contribution is None
        or plan is None
        or program is None
    ):
        raise ValueError("Experiment execution binding is incomplete")
    require_study_unit(definition)
    if type(contribution) is not ResearchBindingContribution:
        raise TypeError("Experiment execution binding contribution must be typed")
    require_research_plan(plan)
    if type(program) is not NoetriumUnit or not program.has_trait("experiment.compilation"):
        raise TypeError("Experiment execution program must be experiment.compilation Unit")
    if research_plan_value(plan, "definition_digest") != study_definition_digest(definition):
        raise ValueError("Experiment definition projection drifted")
    if research_plan_value(plan, "binding_digest") != contribution.contribution_digest:
        raise ValueError("Experiment binding contribution drifted")
    if experiment_compilation_plan(program) != research_plan_study(plan):
        raise ValueError("Experiment program is not derived from authoritative research plan")
    with _VALIDATED_EXPERIMENT_EXECUTION_BINDINGS_LOCK:
        _VALIDATED_EXPERIMENT_EXECUTION_BINDINGS[binding_digest] = None
        if (
            len(_VALIDATED_EXPERIMENT_EXECUTION_BINDINGS)
            > _VALIDATED_EXPERIMENT_EXECUTION_BINDINGS_LIMIT
        ):
            oldest = next(iter(_VALIDATED_EXPERIMENT_EXECUTION_BINDINGS))
            if oldest != binding_digest:
                _VALIDATED_EXPERIMENT_EXECUTION_BINDINGS.pop(oldest, None)
    return value


@runtime_checkable
class ResearchExperimentReconciliationPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def reconcile(
        self,
        execution: ResearchExperimentExecutionBindingView,
        *,
        machine_id: str,
        execution_cut_id: str,
        graph_node_id: str,
        semantic_digest: str,
        binding_digest: str,
        attempt_id: str,
    ) -> ResearchNodeReconciliationProof: ...


@runtime_checkable
class ResearchScientificInputBoundStudyExecutionPort(
    BoundStudyExecutionPort,
    Protocol,
):
    def bind_scientific_inputs(
        self,
        inputs: JsonObject,
    ) -> BoundStudyExecutionPort: ...


@dataclass(frozen=True, slots=True)
class ResearchExperimentRuntimeBinding:
    """Dynamic provider binding for one compiled Research Experiment node."""

    execution_binding_digest: str
    study_plan_digest: str
    research_binding_digest: str
    adapter: BoundStudyExecutionPort
    reconciliation: ResearchExperimentReconciliationPort
    adapter_identity_digest: str
    reconciliation_identity_digest: str
    resource_demand: ResourceCompetitionDemand | None = None
    runtime_binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(
            self.execution_binding_digest,
            "experiment runtime binding execution_binding_digest",
        )
        require_sha256(
            self.study_plan_digest,
            "experiment runtime binding study_plan_digest",
        )
        require_sha256(
            self.research_binding_digest,
            "experiment runtime binding research_binding_digest",
        )
        if not isinstance(self.adapter, BoundStudyExecutionPort):
            raise TypeError(
                "experiment runtime binding adapter must satisfy BoundStudyExecutionPort"
            )
        if not isinstance(self.reconciliation, ResearchExperimentReconciliationPort):
            raise TypeError(
                "experiment runtime binding reconciliation must satisfy "
                "ResearchExperimentReconciliationPort"
            )
        if self.reconciliation.identity_digest != self.reconciliation_identity_digest:
            raise ValueError("experiment reconciliation identity digest drifted")
        if self.resource_demand is not None and not isinstance(
            self.resource_demand,
            ResourceCompetitionDemand,
        ):
            raise TypeError(
                "experiment runtime resource_demand must be ResourceCompetitionDemand"
            )
        for field_name, value in (
            ("adapter_identity_digest", self.adapter_identity_digest),
            ("reconciliation_identity_digest", self.reconciliation_identity_digest),
        ):
            require_sha256(value, f"experiment runtime binding {field_name}")
        object.__setattr__(
            self,
            "runtime_binding_digest",
            canonical_digest(
                {
                    "execution_binding_digest": self.execution_binding_digest,
                    "study_plan_digest": self.study_plan_digest,
                    "research_binding_digest": self.research_binding_digest,
                    "adapter_identity_digest": self.adapter_identity_digest,
                    "reconciliation_identity_digest": self.reconciliation_identity_digest,
                    "resource_demand_digest": (
                        None
                        if self.resource_demand is None
                        else canonical_digest(self.resource_demand)
                    ),
                }
            ),
        )

    def validate_execution_binding(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> None:
        execution = require_experiment_execution_binding(execution)
        assert execution.experiment_program is not None
        assert execution.research_plan is not None
        if (
            self.execution_binding_digest != execution.binding_digest
            or self.study_plan_digest
            != study_plan_digest(experiment_compilation_plan(execution.experiment_program))
            or self.research_binding_digest
            != research_plan_value(execution.research_plan, "binding_digest")
        ):
            raise ValueError(
                "experiment runtime binding does not belong to Research execution binding"
            )


@runtime_checkable
class ResearchExperimentRuntimeBindingPort(Protocol):
    def resolve(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentRuntimeBinding: ...


__all__ = [
    "ResearchExperimentCompilationMissing",
    "ResearchExperimentCompilationPort",
    "ResearchExperimentExecutionBindingView",
    "ResearchExperimentReconciliationPort",
    "ResearchExperimentRuntimeBinding",
    "ResearchExperimentRuntimeBindingPort",
    "ResearchScientificInputBoundStudyExecutionPort",
    "require_experiment_execution_binding",
]
