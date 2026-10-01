from __future__ import annotations

import importlib
from pathlib import Path

from noetrium_platform.research.execution.machines.api import (
    ResearchProgram as MachineResearchProgram,
)
from research.reproductions.contracts import (
    ReproductionAssetKind,
    ReproductionDefinition,
)
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    resolve_research_program_bindings,
)


def _definitions() -> tuple[ReproductionDefinition, ...]:
    root = Path(__file__).resolve().parents[1] / "research" / "reproductions"
    rows = []
    for path in sorted(root.glob("*/definition.py")):
        module = importlib.import_module(
            f"research.reproductions.{path.parent.name}.definition"
        )
        value = getattr(module, "REPRODUCTION", None)
        if type(value) is not ReproductionDefinition:
            raise TypeError(
                f"{path.parent.name} has no typed REPRODUCTION definition"
            )
        rows.append(value)
    return tuple(rows)


def test_method_aggregate_has_no_legacy_peer_research_program_assets() -> None:
    definitions = _definitions()
    legacy_assets = tuple(
        (definition.package, asset.path)
        for definition in definitions
        for asset in definition.assets
        if asset.kind is ReproductionAssetKind.RESEARCH_PROGRAM
    )
    assert legacy_assets == ()
    assert all(resolve_research_program_bindings(definition) == () for definition in definitions)


def test_method_reproductions_bind_all_declared_child_machine_digests() -> None:
    for definition in _definitions():
        kinds = {row.kind for row in definition.assets}
        if not {
            ReproductionAssetKind.METHOD_PROGRAM,
            ReproductionAssetKind.STUDY,
        }.issubset(kinds):
            continue
        machine_bindings = resolve_research_program_bindings(definition)
        program = compile_reproduction_research_program(definition)
        method = next(
            row for row in program.definitions if row.definition_id == "method"
        )
        node = next(row for row in program.nodes if row.node_id == "reproduction")
        expected = tuple(
            {
                "asset_path": row.asset.path,
                "module": row.module,
                "qualname": row.qualname,
                "program_id": row.program_id,
                "machine_kind": row.machine_kind,
                "program_digest": row.program_digest,
            }
            for row in machine_bindings
        )
        assert method.config["research_program_dependencies"] == expected
        assert node.config["research_program_dependencies"] == expected
