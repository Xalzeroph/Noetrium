from __future__ import annotations

from importlib.resources import files
import json

from noetrium_platform.foundation.governance.system_registry.api import system_catalog
import noetrium_platform.research.execution.machines.api as research_program_api


def test_research_program_authoring_is_execution_component_of_public_authority() -> None:
    by_key = {row.identity.key: row for row in system_catalog()}
    execution = by_key["execution"]
    components = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("components.json")
        .read_text(encoding="utf-8")
    )
    component = components["execution/research_program"]

    assert "execution/research_program" not in by_key
    assert execution.canonical_authority_key == "execution"
    assert execution.downstream_surface.value == "public"
    assert "research.program" in execution.provides
    assert "runtime.program" in execution.provides
    assert component["system"] == "execution"
    assert component["node_kind"] == "facet"
    assert component["package_prefix"] == "noetrium_platform.research.execution.machines"


def test_research_program_public_api_exposes_authoring_not_interpreter_internals() -> None:
    exported = set(research_program_api.__all__)
    required = {
        "ResearchProgram",
        "ResearchProgramBuilder",
        "ResearchProgramHost",
        "ResearchHostOperation",
        "ProgramHandlerRegistry",
        "ProgramNodeRequest",
        "ProgramNodeResult",
        "RuntimeProgramBuilder",
        "RuntimeModuleBuilder",
        "RuntimeProgramComposer",
        "ContextProgram",
        "CapabilityProgram",
        "ModelInvocationProgram",
        "LogicalSchedulingProgram",
        "SynchronizationProgram",
        "RecoveryProgram",
        "InterventionProgram",
        "VisibilityProgram",
        "ResearchMachineSessionPort",
        "ResearchMachineRunPort",
    }
    forbidden = {
        "PROGRAM_COMMANDS",
        "PROGRAMMABLE_MACHINE_KINDS",
        "ProgrammableMachineInterpreter",
        "ResearchMachineRun",
        "core_program_handlers",
        "programmable_machine_families",
        "programmable_machine_family",
    }
    assert required <= exported
    assert not (forbidden & exported)


def test_research_program_public_api_exports_resolve() -> None:
    for name in research_program_api.__all__:
        assert hasattr(research_program_api, name), name
