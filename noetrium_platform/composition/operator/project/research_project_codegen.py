from __future__ import annotations

import re

from noetrium_platform.foundation.kernel.kernel import thaw_json
from noetrium_platform.product.api import (
    ResearchDefinition,
    ResearchDefinitionKind,
    ResearchDefinitionRef,
    ResearchDependency,
    ResearchInputBinding,
    ResearchNode,
    ResearchNodeKind,
    ResearchOutputSpec,
    ResearchPortfolio,
    ResearchProjectBlueprint,
    ResearchProgram,
    ResearchValueKind,
)


_PY_SYMBOL = re.compile(r"[^A-Za-z0-9_]+")


def _slot_symbol(ref: ResearchDefinitionRef) -> str:
    base = _PY_SYMBOL.sub("_", f"{ref.program_id}__{ref.definition_id}").strip("_")
    if not base or base[0].isdigit():
        base = "slot_" + base
    return base


def default_research_project_blueprint(project_id: str) -> ResearchProjectBlueprint:
    definitions = (
        ResearchDefinition("benchmark", ResearchDefinitionKind.BENCHMARK),
        ResearchDefinition("method", ResearchDefinitionKind.METHOD),
        ResearchDefinition("primary-metric", ResearchDefinitionKind.METRIC),
    )
    nodes = (
        ResearchNode(
            "main",
            ResearchNodeKind.EXPERIMENT,
            ("benchmark", "method"),
            (ResearchOutputSpec("trajectory", ResearchValueKind.ARTIFACT),),
        ),
        ResearchNode(
            "evaluate",
            ResearchNodeKind.EVALUATION,
            ("primary-metric",),
            (ResearchOutputSpec("score", ResearchValueKind.METRIC),),
        ),
        ResearchNode(
            "analysis",
            ResearchNodeKind.ANALYSIS,
            (),
            (ResearchOutputSpec("claim-evidence", ResearchValueKind.EVIDENCE),),
        ),
    )
    dependencies = (
        ResearchDependency(
            "main",
            "evaluate",
            (
                ResearchInputBinding(
                    "trajectory",
                    "trajectory",
                    ResearchValueKind.ARTIFACT,
                ),
            ),
        ),
        ResearchDependency.after("evaluate", "analysis"),
    )
    program = ResearchProgram(project_id, definitions, nodes, dependencies)
    return ResearchProjectBlueprint(
        ResearchPortfolio(project_id, (program,)),
        (
            ResearchDefinitionRef(project_id, "benchmark"),
            ResearchDefinitionRef(project_id, "method"),
            ResearchDefinitionRef(project_id, "primary-metric"),
        ),
    )


def _literal(value: object) -> str:
    return repr(thaw_json(value))


def _outputs(outputs: tuple[ResearchOutputSpec, ...]) -> str:
    if not outputs:
        return "()"
    rows = ", ".join(
        (
            "api.ResearchOutputSpec("
            f"{output.name!r}, api.ResearchValueKind.{output.kind.name}"
            ")"
        )
        for output in outputs
    )
    return f"({rows},)"


def _bindings(bindings: tuple[ResearchInputBinding, ...]) -> str:
    if not bindings:
        return "()"
    rows = ", ".join(
        (
            "api.ResearchInputBinding("
            f"{binding.input_name!r}, {binding.output_name!r}, "
            f"api.ResearchValueKind.{binding.kind.name}"
            ")"
        )
        for binding in bindings
    )
    return f"({rows},)"


def render_research_slots(blueprint: ResearchProjectBlueprint) -> str:
    if type(blueprint) is not ResearchProjectBlueprint:
        raise TypeError("research slot rendering requires typed blueprint")
    lines = [
        '"""User-owned research implementation slots.',
        "",
        "Fill only these functions with paper/benchmark/metric-specific semantics.",
        "Research topology, scheduling, evidence, checkpointing and recovery remain",
        "platform-owned.",
        '"""',
        "",
    ]
    for slot in blueprint.implementation_slots:
        symbol = _slot_symbol(slot)
        lines.extend(
            (
                f"def {symbol}(*args, **kwargs):",
                f"    \"\"\"Fill implementation for {slot.program_id}:{slot.definition_id}.\"\"\"",
                "    raise NotImplementedError(",
                f"        {('fill research slot ' + slot.program_id + ':' + slot.definition_id)!r}",
                "    )",
                "",
                "",
            )
        )
    names = ", ".join(
        repr(_slot_symbol(slot))
        for slot in blueprint.implementation_slots
    )
    lines.append(f"__all__ = [{names}]")
    lines.append("")
    return "\n".join(lines)


def render_research_module(blueprint: ResearchProjectBlueprint) -> str:
    if type(blueprint) is not ResearchProjectBlueprint:
        raise TypeError("research module rendering requires typed blueprint")
    slot_keys = {
        (slot.program_id, slot.definition_id): slot
        for slot in blueprint.implementation_slots
    }
    lines = [
        '"""AUTO-GENERATED Research OS topology. Edit research.blueprint.json, not this file."""',
        "from noetrium import api",
        "from . import slots as _slots",
        "",
        f"BLUEPRINT_DIGEST = {blueprint.blueprint_digest!r}",
        "",
    ]
    program_vars: list[tuple[str, str]] = []
    for index, program in enumerate(blueprint.portfolio.programs):
        builder = f"_builder_{index}"
        program_var = f"_program_{index}"
        program_vars.append((program.program_id, program_var))
        lines.append(
            f"{builder} = api.ResearchProgramBuilder({program.program_id!r})"
        )
        for definition in program.definitions:
            slot = slot_keys.get((program.program_id, definition.definition_id))
            implementation = (
                "None"
                if slot is None
                else f"_slots.{_slot_symbol(slot)}"
            )
            lines.extend(
                (
                    f"{builder}.definition(",
                    f"    {definition.definition_id!r},",
                    f"    kind=api.ResearchDefinitionKind.{definition.kind.name},",
                    f"    implementation={implementation},",
                    f"    config={_literal(definition.config)},",
                    ")",
                )
            )
        for node in program.nodes:
            lines.extend(
                (
                    f"{builder}.node(",
                    f"    {node.node_id!r},",
                    f"    kind=api.ResearchNodeKind.{node.kind.name},",
                    f"    definitions={node.definition_ids!r},",
                    f"    outputs={_outputs(node.outputs)},",
                    f"    config={_literal(node.config)},",
                    ")",
                )
            )
        for dependency in program.dependencies:
            lines.extend(
                (
                    f"{builder}.depends(",
                    f"    {dependency.downstream_node_id!r},",
                    f"    {dependency.upstream_node_id!r},",
                    f"    bindings={_bindings(dependency.bindings)},",
                    ")",
                )
            )
        lines.extend((f"{program_var} = {builder}.freeze()", ""))

    lines.append(
        f"_portfolio = api.ResearchPortfolioBuilder({blueprint.portfolio.portfolio_id!r})"
    )
    for _program_id, program_var in program_vars:
        lines.append(f"_portfolio.program({program_var})")
    for dependency in blueprint.portfolio.dependencies:
        lines.extend(
            (
                "_portfolio.depends(",
                f"    downstream_program_id={dependency.downstream.program_id!r},",
                f"    downstream_node_id={dependency.downstream.node_id!r},",
                f"    upstream_program_id={dependency.upstream.program_id!r},",
                f"    upstream_node_id={dependency.upstream.node_id!r},",
                f"    bindings={_bindings(dependency.bindings)},",
                ")",
            )
        )
    lines.extend(
        (
            "PORTFOLIO = _portfolio.freeze()",
            "PROGRAMS = PORTFOLIO.programs",
            "",
            '__all__ = ["BLUEPRINT_DIGEST", "PORTFOLIO", "PROGRAMS"]',
            "",
        )
    )
    return "\n".join(lines)


def render_generated_test_module(
    package: str,
    blueprint: ResearchProjectBlueprint,
) -> str:
    expected_programs = tuple(
        program.program_id for program in blueprint.portfolio.programs
    )
    expected_nodes = {
        program.program_id: tuple(node.node_id for node in program.nodes)
        for program in blueprint.portfolio.programs
    }
    expected_definitions = {
        program.program_id: tuple(
            definition.definition_id
            for definition in program.definitions
        )
        for program in blueprint.portfolio.programs
    }
    return f'''import unittest

from noetrium import api
from {package}.research import BLUEPRINT_DIGEST, PORTFOLIO


class GeneratedProjectTests(unittest.TestCase):
    def test_project_compiles_from_one_top_level_blueprint(self):
        self.assertIsInstance(PORTFOLIO, api.ResearchPortfolio)
        self.assertEqual(BLUEPRINT_DIGEST, {blueprint.blueprint_digest!r})
        self.assertEqual(
            tuple(program.program_id for program in PORTFOLIO.programs),
            {expected_programs!r},
        )

    def test_generated_topology_matches_blueprint(self):
        by_id = {{program.program_id: program for program in PORTFOLIO.programs}}
        self.assertEqual(
            {{
                program_id: tuple(node.node_id for node in program.nodes)
                for program_id, program in by_id.items()
            }},
            {expected_nodes!r},
        )
        self.assertEqual(
            {{
                program_id: tuple(
                    definition.definition_id
                    for definition in program.definitions
                )
                for program_id, program in by_id.items()
            }},
            {expected_definitions!r},
        )


if __name__ == "__main__":
    unittest.main()
'''


__all__ = [
    "default_research_project_blueprint",
    "render_generated_test_module",
    "render_research_module",
    "render_research_slots",
]
