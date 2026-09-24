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


__all__ = ["build_bound_research", "build_research"]
