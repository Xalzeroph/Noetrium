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


__all__ = ["build_research"]
