from __future__ import annotations

from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthority,
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


class _ExperimentBindings:
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
        experiment_bindings=_ExperimentBindings(),
        reproduction_capabilities=reproduction_capabilities,
        benchmarks=benchmarks,
    )

    assert type(bundle) is ReproductionFleetExecutionAuthorities
    assert bundle.benchmark_resolver is benchmarks
    assert type(bundle.research_bindings) is ResearchBindingAuthority
    assert type(bundle.experiment_bindings) is _ExperimentBindings
    assert bundle.capability_resolver is reproduction_capabilities
