"""Concrete Operator application composition.

The Product/Operator package owns only product contracts and pure routing.
All cross-layer control-plane implementations live here.
"""
from .wiring.cli import main as diagnose_main
from .wiring.research import main as research_main

__all__ = ["diagnose_main", "research_main"]
