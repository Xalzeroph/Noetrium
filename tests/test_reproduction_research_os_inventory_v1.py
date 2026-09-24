from __future__ import annotations

import importlib
from pathlib import Path

from noetrium import api
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_lowering import (
    compile_research_os_lowering,
)
from research.reproductions.contracts import (
    ReproductionAssetKind,
    ReproductionDefinition,
)
from research.reproductions.research_os import (
    compile_reproduction_portfolio,
    compile_reproduction_research_program,
    resolve_method_program_binding,
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


def test_every_executable_study_reproduction_compiles_to_current_research_os() -> None:
    definitions = _definitions()
    eligible = tuple(row for row in definitions if _research_os_ready(row))
    assert eligible

    compiled_packages: list[str] = []
    for definition in eligible:
        kinds = {asset.kind for asset in definition.assets}
        program = compile_reproduction_research_program(definition)
        assert program.program_id == definition.identity.method_id
        assert len(program.nodes) == 1
        node = program.nodes[0]
        assert node.node_id == "reproduction"
        assert node.kind is api.ResearchNodeKind.EXPERIMENT
        assert node.outputs == (
            api.ResearchOutputSpec("report", api.ResearchValueKind.ARTIFACT),
        )

        if ReproductionAssetKind.METHOD_PROGRAM in kinds:
            binding = resolve_method_program_binding(definition)
            method_definition = next(
                row for row in program.definitions if row.definition_id == "method"
            )
            assert type(method_definition.implementation) is (
                api.ResearchMethodProgramImplementation
            )
            assert method_definition.implementation.program_digest == (
                binding.program_digest
            )
        else:
            machine_bindings = resolve_research_program_bindings(definition)
            assert machine_bindings
            machine_definitions = tuple(
                row
                for row in program.definitions
                if row.definition_id.startswith("machine.")
            )
            assert len(machine_definitions) == len(machine_bindings)

        portfolio = api.ResearchPortfolio(
            f"{definition.identity.method_id}.migration-gate",
            (program,),
        )
        revision = api.ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (),
            "reproduction migration gate",
        )
        graph = compile_research_portfolio_graph(revision, portfolio)
        graph.node(f"{definition.identity.method_id}::reproduction")
        compiled_packages.append(definition.package)

    assert tuple(sorted(compiled_packages)) == tuple(
        sorted(row.package for row in eligible)
    )


def test_all_ready_reproductions_compile_as_one_multi_paper_portfolio() -> None:
    definitions = tuple(row for row in _definitions() if _research_os_ready(row))
    portfolio = compile_reproduction_portfolio(
        "repository-reproductions.current-research-os",
        definitions,
    )
    assert len(portfolio.programs) == len(definitions)
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "all executable reproductions on current Research OS",
    )
    graph = compile_research_portfolio_graph(revision, portfolio)
    assert len(graph.nodes) == len(definitions)
    assert {node.node.node_id for node in graph.nodes} == {"reproduction"}
    assert {node.node.kind for node in graph.nodes} == {
        api.ResearchNodeKind.EXPERIMENT
    }

def test_method_program_bindings_also_lower_exactly_on_method_nodes() -> None:
    # The experiment lane resolves through Experimentation closure.  This
    # complementary check proves the same frozen MethodProgram binding lowers
    # directly to UMM without wrapper semantics.
    for definition in _definitions():
        kinds = {asset.kind for asset in definition.assets}
        if ReproductionAssetKind.METHOD_PROGRAM not in kinds:
            continue
        binding = resolve_method_program_binding(definition)
        builder = api.ResearchProgramBuilder(definition.identity.method_id)
        builder.method_program(
            "method",
            module=binding.module,
            qualname=binding.qualname,
        )
        builder.method_node("method", definitions=("method",))
        program = builder.freeze()
        portfolio = api.ResearchPortfolio(
            f"{definition.identity.method_id}.method-gate",
            (program,),
        )
        revision = api.ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (),
            "MethodProgram lowering gate",
        )
        lowering = compile_research_os_lowering(
            compile_research_portfolio_graph(revision, portfolio)
        )
        lowered = lowering.node(
            f"{definition.identity.method_id}::method"
        )
        assert len(lowered.method_programs) == 1
        assert lowered.method_programs[0].program.program_digest == (
            binding.program_digest
        )
