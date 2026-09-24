from __future__ import annotations

from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthority,
)
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentRuntimeComponents,
)
from research.reproductions.execution_authority import (
    compose_repository_fleet_execution_authorities,
)
from research.reproductions.fleet import ReproductionFleetExecutionAuthorities


class _Manifests:
    def resolve(self, definition):
        raise AssertionError(definition)


class _ResearchCapabilities:
    def resolve(self, requirement, context):
        raise AssertionError((requirement, context))


class _Participants:
    def resolve(self, requirement, context):
        raise AssertionError((requirement, context))


class _Models:
    def resolve(self, requirement, context):
        raise AssertionError((requirement, context))


class _ExperimentStudyExecution:
    def resolve(self, closure):
        raise AssertionError(closure)


class _ExperimentAggregation:
    def resolve(self, closure):
        raise AssertionError(closure)


class _ExperimentReconciliation:
    def resolve(self, closure):
        raise AssertionError(closure)


class _ReproductionCapabilities:
    def resolve(self, requirement):
        raise AssertionError(requirement)


class _Benchmarks:
    def resolve(self, definition, study_factory):
        raise AssertionError((definition, study_factory))


def test_repository_fleet_authority_composition_has_one_research_binding_authority() -> None:
    reproduction_capabilities = _ReproductionCapabilities()
    benchmarks = _Benchmarks()
    bundle = compose_repository_fleet_execution_authorities(
        manifests=_Manifests(),
        research_capabilities=_ResearchCapabilities(),
        participants=_Participants(),
        models=_Models(),
        experiment_study_execution=_ExperimentStudyExecution(),
        experiment_aggregation=_ExperimentAggregation(),
        experiment_reconciliation=_ExperimentReconciliation(),
        reproduction_capabilities=reproduction_capabilities,
        benchmarks=benchmarks,
        authority_manifest_digest="b" * 64,
    )

    assert type(bundle) is ReproductionFleetExecutionAuthorities
    assert bundle.benchmark_resolver is benchmarks
    assert type(bundle.research_bindings) is ResearchBindingAuthority
    assert (
        type(bundle.experiment_runtime_components)
        is ResearchOSExperimentRuntimeComponents
    )
    assert bundle.authority_manifest_digest == "b" * 64
    assert bundle.capability_resolver is reproduction_capabilities
