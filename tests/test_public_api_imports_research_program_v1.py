from __future__ import annotations

from noetrium_platform.foundation.governance.system_registry.api import (
    system_catalog,
)
import noetrium_platform.research.execution.machines.api as research_program_api


def test_research_program_authoring_is_registered_as_public_execution_facet() -> None:
    descriptor = next(
        row
        for row in system_catalog()
        if row.identity.key == "execution/research_program"
    )
    assert descriptor.package_prefix == (
        "noetrium_platform.research.execution.machines"
    )
    assert descriptor.node_kind.value == "facet"
    assert descriptor.canonical_authority_key == "execution"
    assert descriptor.downstream_surface.value == "public"
    assert descriptor.shape == ("api",)
    assert "research.program" in descriptor.provides
    assert "runtime.program" in descriptor.provides


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
    }
    forbidden = {
        "PROGRAM_COMMANDS",
        "PROGRAMMABLE_MACHINE_KINDS",
        "ProgrammableMachineInterpreter",
        "ResearchMachineRun",
        "ResearchMachineSession",
        "core_program_handlers",
        "programmable_machine_families",
        "programmable_machine_family",
    }
    assert required <= exported
    assert not (forbidden & exported)


def test_research_program_public_api_exports_resolve() -> None:
    for name in research_program_api.__all__:
        assert hasattr(research_program_api, name), name
