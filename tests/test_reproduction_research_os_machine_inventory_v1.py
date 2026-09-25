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


def test_every_declared_research_program_asset_resolves_exact_machine_ir() -> None:
    definitions = _definitions()
    packages: list[str] = []
    asset_count = 0
    program_count = 0

    for definition in definitions:
        assets = tuple(
            row
            for row in definition.assets
            if row.kind is ReproductionAssetKind.RESEARCH_PROGRAM
        )
        if not assets:
            continue
        bindings = resolve_research_program_bindings(definition)
        assert bindings
        assert {row.asset.path for row in bindings} == {
            row.path for row in assets
        }
        for binding in bindings:
            module = importlib.import_module(binding.module)
            program = getattr(module, binding.qualname)
            assert type(program) is MachineResearchProgram
            assert program.program_id == binding.program_id
            assert program.kind.value == binding.machine_kind
            assert program.program_digest == binding.program_digest
        packages.append(definition.package)
        asset_count += len(assets)
        program_count += len(bindings)

    assert packages
    assert len(packages) == len(set(packages))
    assert asset_count >= len(packages)
    assert program_count >= asset_count


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
