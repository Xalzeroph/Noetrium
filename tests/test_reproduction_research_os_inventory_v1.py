from __future__ import annotations

import importlib
from pathlib import Path

from noetrium import api
from noetrium_platform.product import research_os as product_research_os
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_lowering import (
    compile_research_os_lowering,
)
from research.reproductions.contracts import (
    ReproductionAssetKind,
    ReproductionDefinition,
    ReproductionLifecycle,
)
from research.reproductions.research_os import (
    compile_reproduction_portfolio,
    compile_reproduction_research_program,
    resolve_method_binding,
    resolve_research_program_bindings,
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


def _research_os_ready(
    definition: ReproductionDefinition,
) -> bool:
    kinds = {asset.kind for asset in definition.assets}
    return (
        ReproductionAssetKind.STUDY in kinds
        and (
            ReproductionAssetKind.METHOD_PROGRAM in kinds
            or ReproductionAssetKind.RESEARCH_PROGRAM in kinds
        )
    )


def test_every_protocol_bound_reproduction_is_current_research_os_ready() -> None:
    definitions = _definitions()
    protocol_bound = tuple(
        row
        for row in definitions
        if row.lifecycle is ReproductionLifecycle.PROTOCOL_BOUND
    )
    assert len(protocol_bound) >= 91
    missing = tuple(
        sorted(row.package for row in protocol_bound if not _research_os_ready(row))
    )
    assert missing == ()


def test_every_executable_study_reproduction_compiles_to_current_research_os() -> None:
    definitions = _definitions()
    eligible = tuple(row for row in definitions if _research_os_ready(row))
    assert eligible

    compiled_packages: list[str] = []
    for definition in eligible:
        kinds = {asset.kind for asset in definition.assets}
        program = compile_reproduction_research_program(definition)
        assert program.program_id == definition.package
        assert len(program.nodes) == 1
        node = program.nodes[0]
        assert node.node_id == "reproduction"
        assert node.kind is product_research_os.ResearchNodeKind.EXPERIMENT
        assert node.outputs == (
            product_research_os.ResearchOutputSpec("report", product_research_os.ResearchValueKind.ARTIFACT),
        )

        if ReproductionAssetKind.METHOD_PROGRAM in kinds:
            binding = resolve_method_binding(definition)
            method_definition = next(
                row for row in program.definitions if row.definition_id == "method"
            )
            if binding.exact:
                assert type(method_definition.implementation) is (
                    product_research_os.ResearchMethodImplementation
                )
                assert method_definition.implementation.method_digest == (
                    binding.method_digest
                )
            else:
                assert method_definition.implementation is None
                assert method_definition.config["authority"] == (
                    "execution-binding-required"
                )
                assert method_definition.config[
                    "execution_requirement_digests"
                ]
                assert binding.configurer_binding is not None
                assert binding.configurer_binding.unresolved_parameters
        else:
            machine_bindings = resolve_research_program_bindings(definition)
            assert machine_bindings
            machine_definitions = tuple(
                row
                for row in program.definitions
                if row.definition_id.startswith("machine.")
            )
            assert len(machine_definitions) == len(machine_bindings)

        portfolio = product_research_os.ResearchPortfolio(
            f"{definition.package}.migration-gate",
            (program,),
        )
        revision = product_research_os.ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (),
            "reproduction migration gate",
        )
        graph = compile_research_portfolio_graph(revision, portfolio)
        graph.node(f"{definition.package}::reproduction")
        compiled_packages.append(definition.package)

    assert tuple(sorted(compiled_packages)) == tuple(
        sorted(row.package for row in eligible)
    )


def test_all_protocol_bound_reproductions_compile_as_one_multi_paper_portfolio() -> None:
    definitions = tuple(
        row
        for row in _definitions()
        if row.lifecycle is ReproductionLifecycle.PROTOCOL_BOUND
    )
    assert definitions
    assert all(_research_os_ready(row) for row in definitions)
    portfolio = compile_reproduction_portfolio(
        "repository-reproductions.current-research-os",
        definitions,
    )
    assert len(portfolio.programs) == len(definitions)
    revision = product_research_os.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "all executable reproductions on current Research OS",
    )
    graph = compile_research_portfolio_graph(revision, portfolio)
    assert len(graph.nodes) == len(definitions)
    assert {node.node.node_id for node in graph.nodes} == {"reproduction"}
    assert {node.node.kind for node in graph.nodes} == {
        product_research_os.ResearchNodeKind.EXPERIMENT
    }

def test_method_program_bindings_lower_only_when_exact() -> None:
    for definition in _definitions():
        kinds = {asset.kind for asset in definition.assets}
        if ReproductionAssetKind.METHOD_PROGRAM not in kinds:
            continue
        binding = resolve_method_binding(definition)
        program = compile_reproduction_research_program(definition)
        method_definition = next(
            row for row in program.definitions if row.definition_id == "method"
        )
        if not binding.exact:
            assert method_definition.implementation is None
            assert method_definition.config["authority"] == "execution-binding-required"
            assert binding.configurer_binding is not None
            assert binding.configurer_binding.unresolved_parameters
            continue
        implementation = method_definition.implementation
        assert type(implementation) is product_research_os.ResearchMethodImplementation
        assert implementation.method_digest == binding.method_digest
