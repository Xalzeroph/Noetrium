"""Select explicitly linked metric semantics without global Program leakage.

The Unit topology, not the method or Provider, owns the relationship between
PROTOCOL and its Experiment-local measurement declarations.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.product.research_traits import TRAIT_EXPERIMENT, TRAIT_METRIC


def scoped_protocol_metric_symbols(
    program: NoetriumUnit,
    definition: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    """Return the metrics common to every Experiment referencing a PROTOCOL.

    Experiment closure later adds its own metrics. Empty selections are valid
    only for Protocols whose Study directly declares its measurement contract.
    """
    references: list[frozenset[str]] = []
    for node in program.members:
        if not node.has_trait(TRAIT_EXPERIMENT):
            continue
        names = node.attribute("symbol_ids", ())
        if not isinstance(names, (list, tuple)):
            raise TypeError("Experiment symbol references must be a sequence")
        refs = frozenset(str(x) for x in names)
        if definition.symbol_id in refs:
            references.append(refs)
    if not references:
        return ()
    common = set.intersection(*(set(refs) for refs in references))
    return tuple(
        symbol for symbol in program.symbols
        if symbol.has_trait(TRAIT_METRIC) and symbol.symbol_id in common
    )
