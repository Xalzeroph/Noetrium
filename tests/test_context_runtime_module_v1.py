from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal, canonical_digest
from noetrium_platform.research.execution.machines import (
    ContextBlockProgram,
    ContextProgram,
    ContextRenderResult,
    ContextRendererRegistry,
    ContextRuntimeBinding,
    ResearchProgramHost,
    RuntimeProgramComposer,
    context_runtime_module,
    context_runtime_operation,
)


def test_context_program_executes_as_runtime_module_without_second_authority() -> None:
    context = ContextProgram(
        program_id="paper.runtime-context",
        version="1",
        max_chars=512,
        blocks=(
            ContextBlockProgram(
                "instruction",
                "paper.render-instruction",
                priority=100,
                required=True,
            ),
        ),
    )
    renderers = ContextRendererRegistry()
    renderers.register(
        "paper.render-instruction",
        lambda request: ContextRenderResult(
            f"Paper instruction: {request.inputs['instruction']}",
            receipt={"renderer": "paper.render-instruction"},
        ),
        implementation_digest=canonical_digest({
            "renderer": "paper.render-instruction",
            "implementation_revision": 1,
        }),
    )
    binding = ContextRuntimeBinding(context, renderers)
    module = context_runtime_module(context)
    runtime_program = (
        RuntimeProgramComposer(
            program_id="paper.runtime-with-context",
            version="1",
            state_schema="paper.runtime-with-context.state.v1",
            entry_module=module.module_id,
        )
        .module(module)
        .build()
    )
    journal = InMemoryMachineJournal()
    host = ResearchProgramHost(
        host_id="paper.runtime-with-context",
        program=runtime_program,
        operations=(context_runtime_operation(),),
        journal=journal,
        dependency_identity={"context_binding": binding.binding_digest},
    )
    session = host.open_session(
        machine_id="runtime:paper-context",
        instance_identity={"paper": "context-test"},
        binding=binding,
    )
    session.start({}, command_id="runtime:paper-context:start")
    commit = session.step(
        {"context_inputs": {"instruction": "use a custom history policy"}},
        command_id="runtime:paper-context:project",
    )

    assert commit.accepted_status.value == "completed"
    projection = session.previous_value
    assert projection["text"] == (
        "\n[instruction]\n"
        "Paper instruction: use a custom history policy\n"
    )
    assert projection["context_program_digest"] == context.program_digest
    assert projection["context_binding_digest"] == binding.binding_digest

    durable = session.data["last_context_projection"]
    assert durable["context_program_digest"] == context.program_digest
    assert durable["context_binding_digest"] == binding.binding_digest
    assert durable["text_digest"] == canonical_digest(projection["text"])
    assert "text" not in durable
    assert durable["receipts"]["instruction"]["renderer"] == (
        "paper.render-instruction"
    )

    head = journal.latest("runtime:paper-context")
    assert head is not None
    assert head.revision == 2



def test_context_binding_changes_with_renderer_implementation_identity() -> None:
    context = ContextProgram(
        program_id="paper.context-identity",
        version="1",
        max_chars=128,
        blocks=(
            ContextBlockProgram(
                "instruction",
                "paper.render-instruction",
                required=True,
            ),
        ),
    )

    def renderer(request):
        return ContextRenderResult(str(request.inputs["instruction"]))

    first = ContextRendererRegistry()
    first.register(
        "paper.render-instruction",
        renderer,
        implementation_digest=canonical_digest({
            "renderer": "paper.render-instruction",
            "implementation_revision": 1,
        }),
    )
    second = ContextRendererRegistry()
    second.register(
        "paper.render-instruction",
        renderer,
        implementation_digest=canonical_digest({
            "renderer": "paper.render-instruction",
            "implementation_revision": 2,
        }),
    )

    assert ContextRuntimeBinding(context, first).binding_digest != (
        ContextRuntimeBinding(context, second).binding_digest
    )
