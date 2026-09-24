"""Research reproduction workspace authoring surface.

This repository workspace follows the same top-level contract generated for an
external Noetrium project: callers ask for one ResearchPortfolio and never need
to know which paper owns MethodProgram, ResearchProgram, Study, benchmark, or
other scientific IR assets.

Paper packages remain the sole owners of paper-specific semantics. Platform
wiring is compiled centrally through Research OS.
"""
from __future__ import annotations

from noetrium import api


def build_research() -> api.ResearchPortfolio:
    """Compile every executable reproduction into one current Research OS portfolio."""
    from .research_os import compile_repository_reproduction_portfolio

    return compile_repository_reproduction_portfolio(
        "repository-reproductions.current-research-os"
    )




def execution_request(
    package: str,
    study_factory: str,
    benchmark: object,
    *,
    benchmark_split_ids: tuple[str, ...],
) -> object:
    """Declare one exact scientific execution lane without platform wiring.

    Split selection is explicit scientific authority. Passing an empty tuple is
    valid only for Studies that have no external benchmark split axis.
    """

    from .research_os import ReproductionExecutionRequest

    return ReproductionExecutionRequest(
        package,
        study_factory,
        benchmark,
        benchmark_split_ids,
    )


def build_execution_research(
    requests: tuple[object, ...],
    *,
    capability_resolver: object | None = None,
) -> api.ResearchPortfolio:
    """Compile scientific lane requests into a fully bound ResearchPortfolio.

    Benchmark split expansion, typed paper-option expansion, capability closure
    resolution and execution-binding identity are compiler/platform concerns.
    """

    from .research_os import (
        ReproductionCapabilityRequirementResolverPort,
        ReproductionExecutionRequest,
        compile_resolved_reproduction_portfolio,
    )

    if type(requests) is not tuple or not requests:
        raise ValueError("execution research requires a non-empty request tuple")
    if any(type(row) is not ReproductionExecutionRequest for row in requests):
        raise TypeError(
            "execution research requires typed ReproductionExecutionRequest values"
        )
    if capability_resolver is not None and not isinstance(
        capability_resolver,
        ReproductionCapabilityRequirementResolverPort,
    ):
        raise TypeError(
            "execution research capability_resolver must satisfy the typed resolver port"
        )
    return compile_resolved_reproduction_portfolio(
        "repository-reproductions.execution-research",
        requests,
        capability_resolver=capability_resolver,
    )


def build_bound_research(bindings: tuple[object, ...]) -> api.ResearchPortfolio:
    """Compile exact paper-owned execution bindings into one runnable portfolio.

    The caller supplies only scientific closure values. Study/Method/ResearchMachine
    lowering and all platform wiring remain owned by the central Research OS compiler.
    """
    from .research_os import (
        ReproductionExecutionBinding,
        compile_bound_reproduction_portfolio,
    )

    if type(bindings) is not tuple or not bindings:
        raise ValueError("bound research requires a non-empty binding tuple")
    if any(type(row) is not ReproductionExecutionBinding for row in bindings):
        raise TypeError("bound research requires typed ReproductionExecutionBinding values")
    return compile_bound_reproduction_portfolio(
        "repository-reproductions.bound-research",
        bindings,
    )


__all__ = [
    "build_bound_research",
    "build_execution_research",
    "build_research",
    "execution_request",
]
