from __future__ import annotations


def is_composition_module(module: str) -> bool:
    """Return True when a module belongs to an explicit composition plane.

    Composition owns wiring, not domain authority.  It is intentionally outside the
    authoritative system dependency DAG and may see concrete implementations from
    multiple systems in order to bind their Ports.
    """

    return "composition" in module.split(".")


__all__ = ["is_composition_module"]
