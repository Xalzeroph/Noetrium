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
    compile_reproduction_research_program,
    resolve_method_program_binding,
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


def test_every_method_program_study_reproduction_compiles_to_current_research_os() -> None:
    definitions = _definitions()
    compiled_packages: list[str] = []

    for definition in definitions:
        kinds = {asset.kind for asset in definition.assets}
        if not {
            ReproductionAssetKind.METHOD_PROGRAM,
            ReproductionAssetKind.STUDY,
        }.issubset(kinds):
            continue

        binding = resolve_method_program_binding(definition)
        program = compile_reproduction_research_program(definition)
        assert program.program_id == definition.identity.method_id
        assert len(program.nodes) == 1
        node = program.nodes[0]
        assert node.node_id == "reproduction"
        assert node.kind is api.ResearchNodeKind.EXPERIMENT
        assert node.outputs == (
            api.ResearchOutputSpec("report", api.ResearchValueKind.ARTIFACT),
        )

        method_definition = next(
            row for row in program.definitions if row.definition_id == "method"
        )
        assert type(method_definition.implementation) is (
            api.ResearchMethodProgramImplementation
        )
        assert method_definition.implementation.program_digest == (
            binding.program_digest
        )

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
        # Experimentation lowering requires a closure to execute, but the
        # MethodProgram implementation identity must already be import-resolved
        # and bound into the immutable graph semantics.
        graph_node = graph.node(
            f"{definition.identity.method_id}::reproduction"
        )
        method_source = next(
            row for row in graph_node.definitions
            if row.definition_id == "method"
        )
        assert method_source.implementation_digest == (
            method_definition.implementation_digest
        )
        compiled_packages.append(definition.package)

    assert compiled_packages
    assert len(compiled_packages) == len(set(compiled_packages))


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
