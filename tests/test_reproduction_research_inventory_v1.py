from __future__ import annotations

import importlib
from pathlib import Path

from noetrium_platform.composition.research_execution_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.product.research_control import ResearchGraphRevision
from research.reproductions.contracts import (
    ReproductionAssetKind,
    ReproductionDefinition,
    ReproductionLifecycle,
)
from research.reproductions.research_units import (
    compile_reproduction_portfolio,
    compile_reproduction_research_program,
    resolve_method_binding,
)


def _definitions() -> tuple[ReproductionDefinition, ...]:
    root = Path(__file__).resolve().parents[1] / "research" / "reproductions"
    rows = []
    for path in sorted(root.glob("*/definition.py")):
        package = path.parent.name
        module = importlib.import_module(
            f"research.reproductions.{package}.definition"
        )
        definition = getattr(module, "REPRODUCTION", None)
        if type(definition) is not ReproductionDefinition:
            raise TypeError(f"{package} has no typed REPRODUCTION definition")
        rows.append(definition)
    return tuple(rows)


def _research_ready(definition: ReproductionDefinition) -> bool:
    kinds = {asset.kind for asset in definition.assets}
    return (
        ReproductionAssetKind.STUDY in kinds
        and ReproductionAssetKind.METHOD_PROGRAM in kinds
    )


def test_every_protocol_bound_reproduction_is_current_research_ready() -> None:
    definitions = _definitions()
    protocol_bound = tuple(
        row
        for row in definitions
        if row.lifecycle is ReproductionLifecycle.PROTOCOL_BOUND
    )
    assert len(protocol_bound) >= 91
    missing = tuple(
        sorted(row.package for row in protocol_bound if not _research_ready(row))
    )
    assert missing == ()


def test_every_executable_study_reproduction_compiles_to_recursive_graph() -> None:
    eligible = tuple(row for row in _definitions() if _research_ready(row))
    assert eligible
    compiled_packages: list[str] = []
    for definition in eligible:
        graph = compile_reproduction_research_program(definition)
        assert graph.graph_id == definition.package
        assert graph.has_trait("research.program")
        assert {"method", "study"} <= {row.symbol_id for row in graph.symbols}
        reproduction = graph.member("reproduction")
        assert reproduction.has_trait("research.experiment")
        assert {"method", "study"} <= set(reproduction.symbol_ids)

        binding = resolve_method_binding(definition)
        assert len(binding.binding_digest) == 64
        if binding.exact:
            assert binding.method_digest is not None
            assert len(binding.method_digest) == 64
        else:
            assert binding.configurer_binding is not None
            assert binding.configurer_binding.unresolved_parameters

        portfolio = compile_reproduction_portfolio(
            f"{definition.package}.migration-gate",
            (definition,),
        )
        revision = ResearchGraphRevision(
            portfolio.unit_id,
            portfolio.unit_digest,
            (),
            "reproduction migration gate",
        )
        compiled = compile_research_portfolio_graph(revision, portfolio)
        compiled.binding(
            f"{portfolio.unit_id}::{definition.package}::reproduction"
        )
        compiled_packages.append(definition.package)

    assert tuple(sorted(compiled_packages)) == tuple(
        sorted(row.package for row in eligible)
    )


def test_protocol_bound_reproductions_form_one_multi_paper_recursive_portfolio() -> None:
    definitions = tuple(
        row
        for row in _definitions()
        if row.lifecycle is ReproductionLifecycle.PROTOCOL_BOUND
    )
    assert definitions
    portfolio = compile_reproduction_portfolio(
        "repository-reproductions.current-research",
        definitions,
    )
    programs = tuple(unit for unit in portfolio.members if unit.has_trait("research.program"))
    assert len(programs) == len(definitions)

    revision = ResearchGraphRevision(
        portfolio.unit_id,
        portfolio.unit_digest,
        (),
        "all executable reproductions on current Research execution",
    )
    compiled = compile_research_portfolio_graph(revision, portfolio)
    assert len(compiled.bindings) == len(definitions)
    assert {binding.graph.graph_id for binding in compiled.bindings} == {"reproduction"}
    assert all(
        binding.graph.has_trait("research.experiment")
        for binding in compiled.bindings
    )


def test_method_bindings_are_reflected_in_program_graph_symbols() -> None:
    for definition in _definitions():
        kinds = {asset.kind for asset in definition.assets}
        if ReproductionAssetKind.METHOD_PROGRAM not in kinds:
            continue
        binding = resolve_method_binding(definition)
        graph = compile_reproduction_research_program(definition)
        assert "method" in {row.symbol_id for row in graph.symbols}
        method = graph.symbol("method")
        assert method.has_trait("research.method")
        assert len(binding.binding_digest) == 64
        if binding.exact:
            assert binding.method_digest is not None
            assert len(binding.method_digest) == 64
        else:
            assert binding.configurer_binding is not None
            assert binding.configurer_binding.unresolved_parameters
