from __future__ import annotations

from importlib.resources import files
import json

from noetrium_platform.foundation.governance.system_registry.api import system_catalog
import noetrium_platform.research.execution.machines.api as executable_unit_api


def test_executable_unit_authoring_is_internal_execution_component() -> None:
    by_key = {row.identity.key: row for row in system_catalog()}
    execution = by_key["execution"]
    components = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("components.json")
        .read_text(encoding="utf-8")
    )
    component = components["execution/executable_unit"]

    assert "execution/executable_unit" not in by_key
    assert execution.canonical_authority_key == "execution"
    assert execution.downstream_surface.value == "metadata_only"
    assert "machine.program" in execution.provides
    assert "runtime.program" in execution.provides
    assert component["system"] == "execution"
    assert component["node_kind"] == "facet"
    assert component["package_prefix"] == "noetrium_platform.research.execution.machines"


def test_executable_unit_adjacent_api_exposes_contracts_not_interpreter_internals() -> None:
    exported = set(executable_unit_api.__all__)
    required = {
        "NoetriumUnit",
        "executable_unit",
        "unit_operation",
        "unit_flow",
        "runtime_module",
        "compose_runtime_program",
        "context_graph",
        "capability_program_graph",
        "model_invocation_program_graph",
        "logical_scheduling_program",
        "synchronization_program",
        "recovery_program",
        "intervention_program",
        "visibility_program",
        "memory_preset_unit",
        "context_block_unit",
        "environment_machine_unit",
        "optimization_preset_unit",
        "UnitExecutionDriverPort",
    }
    forbidden = {
        "MachineProgramBuilder",
        "RuntimeProgramBuilder",
        "RuntimeModuleBuilder",
        "RuntimeProgramComposer",
        "CapabilityProgramBuilder",
        "UNIT_MACHINE_COMMANDS",
        "UNIVERSAL_UNIT_KINDS",
        "UniversalUnitMachine",
        "UnitRun",
        "universal_machine_families",
        "universal_machine_family",
    }
    assert required <= exported
    assert not (forbidden & exported)


def test_executable_unit_adjacent_api_exports_resolve() -> None:
    for name in executable_unit_api.__all__:
        assert hasattr(executable_unit_api, name), name
