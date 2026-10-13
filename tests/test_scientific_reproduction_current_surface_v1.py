from __future__ import annotations

import importlib

from research.reproductions.research_units import (
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


def test_every_executable_reproduction_materializes_current_method_and_program() -> None:
    executable = executable_reproduction_definitions()
    assert len(executable) == 95
    for definition in executable:
        binding = resolve_method_binding(definition)
        assert binding.module.startswith("research.reproductions.")
        assert binding.qualname
        assert binding.entrypoint
        program = compile_reproduction_research_program(definition)
        assert program.unit_id == definition.package
        assert any(unit.unit_id == "method" for unit in program.units("symbol"))
        assert tuple(member.unit_id for member in program.members) == ("reproduction",)
        assert len(binding.binding_digest) == 64
        if binding.exact:
            assert binding.method_digest is not None
            assert len(binding.method_digest) == 64
        else:
            assert binding.configurer_binding is not None
            assert binding.configurer_binding.unresolved_parameters
