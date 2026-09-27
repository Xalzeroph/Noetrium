from __future__ import annotations

import importlib

from research.reproductions.contracts import ReproductionAssetKind
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    resolve_method_binding,
)


def test_all_reproduction_packages_use_current_scientific_surface() -> None:
    definitions = discover_reproduction_definitions()
    assert len(definitions) == 100
    for definition in definitions:
        package = importlib.import_module(f"research.reproductions.{definition.package}")
        assert package.__all__ == ("REPRODUCTION",)
        assert package.REPRODUCTION is definition
        assert all(asset.kind is not ReproductionAssetKind.RESEARCH_PROGRAM for asset in definition.assets)


def test_every_executable_reproduction_materializes_current_method_and_program() -> None:
    executable = executable_reproduction_definitions()
    assert len(executable) == 95
    for definition in executable:
        binding = resolve_method_binding(definition)
        assert binding.module.startswith("research.reproductions.")
        assert binding.qualname
        assert binding.entrypoint
        program = compile_reproduction_research_program(definition)
        assert program.program_id == definition.package
        method = next(row for row in program.definitions if row.definition_id == "method")
        if binding.exact:
            assert method.implementation is not None
            assert method.implementation.method_digest == binding.method_digest
        else:
            assert method.implementation is None
            assert method.config["authority"] == "execution-binding-required"
