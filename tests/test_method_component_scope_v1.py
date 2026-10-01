from __future__ import annotations

import pytest

from noetrium_platform.composition.research_child_machine_runtime import (
    compose_program_method_runtime_inventory,
)
from noetrium_platform.foundation.kernel.kernel import DirectoryMachineJournal
from noetrium_platform.product.research_os import ResearchPortfolioBuilder
from noetrium_platform.research.execution.workflow.api import MethodRuntimePortInventory


def _component_a(call):
    return call.transition(value={"owner": "a"})


def _component_b(call):
    return call.transition(value={"owner": "b"})


def _finish(call):
    return call.transition(value={"ok": True})


def _method_a(method):
    memory = method.memory(
        "shared.memory",
        entrypoint="dispatch",
        state_schema="fixture.memory.a.v1",
    )
    memory.custom("dispatch", "fixture.memory.a.dispatch", _component_a)
    memory.end()
    method.return_node("finish", "fixture.a.finish", _finish)


def _method_b(method):
    memory = method.memory(
        "shared.memory",
        entrypoint="dispatch",
        state_schema="fixture.memory.b.v1",
    )
    memory.custom("dispatch", "fixture.memory.b.dispatch", _component_b)
    memory.end()
    method.return_node("finish", "fixture.b.finish", _finish)


def _program():
    root = ResearchPortfolioBuilder("method-component-scope")
    paper = root.program("paper")
    paper.method("method-a", _method_a, method_id="method-a", entrypoint="finish")
    paper.method("method-b", _method_b, method_id="method-b", entrypoint="finish")
    paper.method_node("run-a", definitions=("method-a",))
    paper.method_node("run-b", definitions=("method-b",))
    return root.freeze().programs[0]


def test_method_owned_host_names_are_scoped_by_selected_method_program(tmp_path) -> None:
    program = _program()
    methods = {
        definition.definition_id: definition.implementation.resolve()
        for definition in program.definitions
        if definition.definition_id in {"method-a", "method-b"}
    }
    assert methods["method-a"].components[0].host_id == "shared.memory"
    assert methods["method-b"].components[0].host_id == "shared.memory"
    assert (
        methods["method-a"].components[0].artifact_digest
        != methods["method-b"].components[0].artifact_digest
    )

    for definition_id, method in methods.items():
        inventory = compose_program_method_runtime_inventory(
            program,
            MethodRuntimePortInventory(),
            method_program_digests=(method.program.program_digest,),
            journal=DirectoryMachineJournal(tmp_path / definition_id),
            max_steps=32,
        )
        assert inventory.child_machines is not None
        registrations = inventory.child_machines.registry.registrations()
        assert len(registrations) == 1
        assert registrations[0].host.host_id == "shared.memory"
        assert (
            registrations[0].host.program.program_digest
            == method.components[0].program.program_digest
        )


def test_multi_method_binding_with_conflicting_logical_host_fails_closed(tmp_path) -> None:
    program = _program()
    methods = [
        definition.implementation.resolve()
        for definition in program.definitions
        if definition.definition_id in {"method-a", "method-b"}
    ]
    with pytest.raises(ValueError, match="host ids must be unique"):
        compose_program_method_runtime_inventory(
            program,
            MethodRuntimePortInventory(),
            method_program_digests=tuple(
                method.program.program_digest for method in methods
            ),
            journal=DirectoryMachineJournal(tmp_path / "ambiguous"),
            max_steps=32,
        )
