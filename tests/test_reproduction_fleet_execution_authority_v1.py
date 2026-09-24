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
from scripts.run_reproduction_fleet import _load_execution_authorities


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


def test_cli_authority_loader_accepts_only_typed_public_factory() -> None:
    module_name = "_noetrium_test_fleet_authority"
    module = ModuleType(module_name)
    module.build = _authorities
    sys.modules[module_name] = module
    try:
        context = object()
        loaded = _load_execution_authorities(module_name + ":build", context)
        assert type(loaded) is ReproductionFleetExecutionAuthorities
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.parametrize(
    "spec",
    (
        "",
        "missing-separator",
        "module:",
        ":factory",
        "module:_private",
        "module:factory:extra",
    ),
)
def test_cli_authority_loader_rejects_ambiguous_or_private_specs(spec: str) -> None:
    with pytest.raises((ValueError, ModuleNotFoundError)):
        _load_execution_authorities(spec, object())


def test_cli_authority_loader_passes_runtime_context_to_factory() -> None:
    module_name = "_noetrium_test_fleet_context"
    module = ModuleType(module_name)
    seen = []

    def build(context):
        seen.append(context)
        return _authorities()

    module.build = build
    sys.modules[module_name] = module
    context = object()
    try:
        _load_execution_authorities(module_name + ":build", context)
    finally:
        sys.modules.pop(module_name, None)
    assert seen == [context]
