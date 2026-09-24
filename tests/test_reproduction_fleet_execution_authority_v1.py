from __future__ import annotations

import sys
from types import ModuleType

import pytest

from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentRuntimeComponents,
)
from research.reproductions.fleet import (
    ReproductionFleetExecutionAuthorities,
)
from scripts.run_reproduction_fleet import _load_authority_materializer


class _BenchmarkResolver:
    authority_digest = "b" * 64

    def resolve(self, definition, study_factory):
        del definition, study_factory
        raise AssertionError("not exercised by authority contract test")


class _ResearchBindings:
    def resolve(self, definition):
        del definition
        raise AssertionError("not exercised by authority contract test")


class _ExperimentStudyExecution:
    def resolve(self, closure):
        del closure
        raise AssertionError("not exercised by authority contract test")


class _ExperimentAggregation:
    def resolve(self, closure):
        del closure
        raise AssertionError("not exercised by authority contract test")


class _ExperimentReconciliation:
    def resolve(self, closure):
        del closure
        raise AssertionError("not exercised by authority contract test")


class _CapabilityResolver:
    def resolve(self, requirement):
        del requirement
        raise AssertionError("not exercised by authority contract test")


def _authorities(_context=None) -> ReproductionFleetExecutionAuthorities:
    return ReproductionFleetExecutionAuthorities(
        benchmark_resolver=_BenchmarkResolver(),
        research_bindings=_ResearchBindings(),
        experiment_runtime_components=ResearchOSExperimentRuntimeComponents(
            _ExperimentStudyExecution(),
            _ExperimentAggregation(),
            _ExperimentReconciliation(),
        ),
        authority_manifest_digest="a" * 64,
        capability_resolver=_CapabilityResolver(),
    )


def test_execution_authorities_require_all_runtime_closure_ports() -> None:
    authorities = _authorities()
    assert isinstance(authorities.benchmark_resolver, _BenchmarkResolver)
    assert isinstance(authorities.research_bindings, _ResearchBindings)
    assert (
        type(authorities.experiment_runtime_components)
        is ResearchOSExperimentRuntimeComponents
    )
    assert authorities.authority_manifest_digest == "a" * 64
    assert isinstance(authorities.capability_resolver, _CapabilityResolver)


def test_cli_materializer_loader_passes_runtime_context_to_factory() -> None:
    class Materializer:
        def materialize_prerequisites(self, requirements):
            raise AssertionError(requirements)

        def materialize_manifests(self, requirements, fleet):
            raise AssertionError((requirements, fleet))

        def materialize_execution_owners(
            self,
            requirements,
            capability_requirements,
            fleet,
            manifests,
        ):
            raise AssertionError(
                (requirements, capability_requirements, fleet, manifests)
            )

    module_name = "_noetrium_test_fleet_materializer_context"
    module = ModuleType(module_name)
    seen = []

    def build(context):
        seen.append(context)
        return Materializer()

    module.build = build
    sys.modules[module_name] = module
    context = object()
    try:
        loaded = _load_authority_materializer(module_name + ":build", context)
    finally:
        sys.modules.pop(module_name, None)

    assert isinstance(loaded, Materializer)
    assert seen == [context]
