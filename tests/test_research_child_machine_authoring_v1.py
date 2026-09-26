from __future__ import annotations

import pytest

from noetrium import api


def _child_dispatch(request: api.ProgramNodeRequest, binding: object) -> api.ProgramNodeResult:
    del binding
    return api.ProgramNodeResult(value={"ok": True})


CHILD_PROGRAM = (
    api.MemoryProgramBuilder.create(
        program_id="test.child-memory",
        version="1",
        state_schema="test.child-memory.state.v1",
        entrypoint="dispatch",
    )
    .custom(
        "dispatch",
        "test.child.dispatch",
        configuration={"kind": "fixture"},
        next_node="dispatch",
    )
    .build()
)


def child_operations() -> tuple[api.ResearchHostOperation, ...]:
    return (
        api.ResearchHostOperation(
            "test.child.dispatch",
            _child_dispatch,
            api.canonical_digest(
                {
                    "operation": "test.child.dispatch",
                    "implementation_revision": 1,
                }
            ),
        ),
    )


def _parent_builder() -> api.ResearchProgramBuilder:
    builder = api.ResearchProgramBuilder("paper")
    builder.definition(
        "root-definition",
        kind=api.ResearchDefinitionKind.CUSTOM,
        config={"kind": "root"},
    )
    builder.node(
        "root",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("root-definition",),
    )
    return builder


def test_child_machine_program_is_explicit_program_scoped_authoring() -> None:
    builder = _parent_builder()
    builder.child_machine_program(
        "test.child-memory",
        program_module=__name__,
        program_qualname="CHILD_PROGRAM",
        operations_module=__name__,
        operations_qualname="child_operations",
    )
    program = builder.freeze()

    child = next(
        row
        for row in program.definitions
        if row.definition_id == "test.child-memory"
    )
    assert child.kind is api.ResearchDefinitionKind.CHILD_MACHINE
    assert isinstance(child.implementation, api.ResearchMachineProgramImplementation)
    assert child.implementation.program_digest == CHILD_PROGRAM.program_digest
    assert all(
        "test.child-memory" not in node.definition_ids
        for node in program.nodes
    )


def test_child_machine_definition_cannot_be_consumed_by_top_level_node() -> None:
    builder = _parent_builder()
    builder.child_machine_program(
        "test.child-memory",
        program_module=__name__,
        program_qualname="CHILD_PROGRAM",
        operations_module=__name__,
        operations_qualname="child_operations",
    )
    builder.node(
        "invalid-child-node",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("test.child-memory",),
    )

    with pytest.raises(ValueError, match="Program-scoped auxiliary"):
        builder.freeze()


def test_child_machine_kind_requires_exact_machine_program_implementation() -> None:
    with pytest.raises(ValueError, match="require an exact ResearchProgram"):
        api.ResearchDefinition(
            "test.child-memory",
            api.ResearchDefinitionKind.CHILD_MACHINE,
            None,
        )


def test_generic_machine_program_cannot_bypass_child_machine_authoring() -> None:
    builder = _parent_builder()
    with pytest.raises(ValueError, match="child_machine_program"):
        builder.machine_program(
            "test.child-memory",
            program_module=__name__,
            program_qualname="CHILD_PROGRAM",
            operations_module=__name__,
            operations_qualname="child_operations",
            kind=api.ResearchDefinitionKind.CHILD_MACHINE,
        )
