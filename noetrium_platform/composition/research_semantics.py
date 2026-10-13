"""Compiler registry for built-in Research Graph semantic traits.

The Research Graph type system remains open. This module only assigns compiler
ownership to Noetrium's built-in semantics; unregistered traits remain metadata
and can be handled by extensions without changing the structural IR.
"""
from __future__ import annotations


from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable

from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    NoetriumUnit,
)
from noetrium_platform.product.research_traits import (
    ORGANIZATIONAL_TRAITS,
    PLATFORM_BINDING_TRAITS,
    SCIENTIFIC_METADATA_TRAITS,
    TRAIT_ABLATION, TRAIT_ANALYSIS, TRAIT_ARTIFACT, TRAIT_BENCHMARK,
    TRAIT_UNIT_ACTIVATION, TRAIT_CLAIM, TRAIT_COHORT, TRAIT_CONFIGURATION,
    TRAIT_DATASET, TRAIT_ENVIRONMENT, TRAIT_EVALUATION, TRAIT_EVIDENCE,
    TRAIT_EXPERIMENT, TRAIT_FACTOR, TRAIT_FIGURE, TRAIT_HYPOTHESIS,
    TRAIT_INTERVENTION, TRAIT_MEASUREMENT, TRAIT_METHOD, TRAIT_METRIC,
    TRAIT_MODEL, TRAIT_OBJECTIVE, TRAIT_OPTIMIZATION, TRAIT_PARTICIPANT,
    TRAIT_PORTFOLIO, TRAIT_PROGRAM, TRAIT_PROTOCOL, TRAIT_PUBLICATION,
    TRAIT_REPORT, TRAIT_ROBUSTNESS, TRAIT_RUN, TRAIT_RUNTIME, TRAIT_SCALING,
    TRAIT_SELECTION, TRAIT_SPLIT, TRAIT_STUDY, TRAIT_TABLE, TRAIT_TASK,
    TRAIT_TREATMENT, TRAIT_TRIAL, TRAIT_TRIAL_PROVIDER, TRAIT_VERIFIER,
)



@dataclass(frozen=True, slots=True)
class ResearchTraitLowering:
    mode: str
    domain: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"unit", "experimentation"}:
            raise ValueError("invalid research trait lowering mode")
        if (self.mode == "unit") != (self.domain is not None):
            raise ValueError(
                "unit research trait lowering requires exactly one semantic domain"
            )
        if self.domain is not None and (
            type(self.domain) is not str or not self.domain.strip()
        ):
            raise ValueError("research executable domain must be non-empty text")


_NODE_LOWERING = MappingProxyType(
    {
        TRAIT_METHOD: ResearchTraitLowering("unit", "method"),
        TRAIT_STUDY: ResearchTraitLowering("experimentation"),
        TRAIT_EXPERIMENT: ResearchTraitLowering("experimentation"),
        TRAIT_TRIAL: ResearchTraitLowering("experimentation"),
        TRAIT_ABLATION: ResearchTraitLowering("experimentation"),
        TRAIT_ROBUSTNESS: ResearchTraitLowering("experimentation"),
        TRAIT_SCALING: ResearchTraitLowering("experimentation"),
        TRAIT_RUN: ResearchTraitLowering("unit", "run"),
        TRAIT_EVALUATION: ResearchTraitLowering(
            "unit", "evaluation"
        ),
        TRAIT_OPTIMIZATION: ResearchTraitLowering(
            "unit", "optimization"
        ),
        TRAIT_ANALYSIS: ResearchTraitLowering(
            "unit", "analysis"
        ),
        TRAIT_SELECTION: ResearchTraitLowering(
            "unit", "analysis"
        ),
        TRAIT_FIGURE: ResearchTraitLowering(
            "unit", "analysis"
        ),
        TRAIT_TABLE: ResearchTraitLowering(
            "unit", "analysis"
        ),
        TRAIT_PUBLICATION: ResearchTraitLowering(
            "unit", "publication"
        ),
        TRAIT_RUNTIME: ResearchTraitLowering(
            "unit", "runtime"
        ),
    }
)



def trait_ids(values: Iterable[str]) -> frozenset[str]:
    return frozenset(values)


def _lowering_for_ids(
    ids: frozenset[str],
    *,
    default_runtime: bool,
) -> ResearchTraitLowering | None:
    matches = tuple(
        (trait_id, semantics)
        for trait_id in ids
        if (semantics := _NODE_LOWERING.get(trait_id)) is not None
    )
    if not matches:
        if default_runtime:
            return _NODE_LOWERING[TRAIT_RUNTIME]
        return None
    first = matches[0][1]
    if any(
        row.mode != first.mode or row.domain != first.domain
        for _trait_id, row in matches[1:]
    ):
        raise ValueError(
            "research semantic traits select incompatible lowering owners: "
            + ", ".join(sorted(trait_id for trait_id, _row in matches))
        )
    return first


def lowering_for_traits(
    values: Iterable[str],
    *,
    default_runtime: bool,
) -> ResearchTraitLowering | None:
    return _lowering_for_ids(
        trait_ids(values),
        default_runtime=default_runtime,
    )


def lowering_for_graph(graph: NoetriumUnit) -> ResearchTraitLowering:
    if type(graph) is not NoetriumUnit:
        raise TypeError("research lowering requires NoetriumUnit")
    # Execution is explicit. A leaf does not become an implicit runtime node
    # merely because it has no children: static paper semantics such as memory
    # spaces, topology annotations and evidence descriptors are legitimate
    # leaf Units. Only a registered executable research trait owns lowering.
    result = _lowering_for_ids(
        graph.trait_ids,
        default_runtime=False,
    )
    if result is None:
        raise ValueError(
            "static NoetriumUnit does not own executable research lowering"
        )
    return result


def graph_is_transparent_container(graph: NoetriumUnit) -> bool:
    if type(graph) is not NoetriumUnit:
        raise TypeError("research transparency check requires NoetriumUnit")
    # Traits describe scientific semantics; they do not, by themselves, create
    # a physical Machine.  Runtime/method/run are explicit execution surfaces.
    # Other unit-domain semantics (analysis/evaluation/optimization/publication
    # and future peers) become executable only when the graph actually binds an
    # executable symbol.  A pure semantic leaf therefore remains in the immutable
    # Unit graph without manufacturing an empty scheduler vertex.
    lowering = _lowering_for_ids(
        graph.trait_ids,
        default_runtime=False,
    )
    if lowering is None:
        return True
    if (
        lowering.mode == "unit"
        and lowering.domain not in {"runtime", "method", "run"}
        and not graph.symbols
        and not graph.symbol_ids
    ):
        return True
    return False



def scientific_metadata_traits(symbol: NoetriumUnit) -> tuple[str, ...]:
    if type(symbol) is not NoetriumUnit:
        raise TypeError("scientific metadata trait resolution requires NoetriumUnit")
    return tuple(sorted(symbol.trait_ids & SCIENTIFIC_METADATA_TRAITS))


def symbol_has_trait(symbol: NoetriumUnit, trait_id: str) -> bool:
    if type(symbol) is not NoetriumUnit:
        raise TypeError("research symbol trait check requires NoetriumUnit")
    return symbol.has_trait(trait_id)


def platform_binding_traits(symbol: NoetriumUnit) -> tuple[str, ...]:
    if type(symbol) is not NoetriumUnit:
        raise TypeError("platform binding trait resolution requires NoetriumUnit")
    return tuple(sorted(symbol.trait_ids & PLATFORM_BINDING_TRAITS))


__all__ = [
    "ResearchTraitLowering",
    "lowering_for_graph",
    "lowering_for_traits",
    "graph_is_transparent_container",
    "platform_binding_traits",
    "scientific_metadata_traits",
    "symbol_has_trait",
    "trait_ids",
]
