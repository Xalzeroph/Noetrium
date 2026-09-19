from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineCommand,
    MachineExecutor,
    MachineIdentity,
    MachineKind,
    ProgramLock,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    ProgramHandlerRegistry,
    ProgramNodeResult,
    ProgrammableMachineInterpreter,
    RuntimeConcern,
    RuleDispatchMode,
    MachineEvent,
    ProgramRule,
    ProgramRuleSet,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
    programmable_machine_family,
)


def _digest(value: object) -> str:
    return canonical_digest(value)


def _lock() -> ProgramLock:
    return ProgramLock(
        code_digest=_digest("runtime-code"),
        dependency_digest=_digest("runtime-deps"),
        schema_digest=_digest("runtime-schema"),
        interpreter_digest=_digest("runtime-interpreter"),
        data_digest=_digest("runtime-data"),
        config_digest=_digest("runtime-config"),
    )


def _machine(program):
    return MachineExecutor(
        identity=MachineIdentity("runtime:paper", MachineKind.RUNTIME, "1", "g1"),
        program=program.machine_program_ref(_lock()),
        journal=InMemoryMachineJournal(),
        family=programmable_machine_family(MachineKind.RUNTIME),
    )


def _command(machine, revision: int, command_id: str, kind: str, payload: object):
    return MachineCommand(
        command_id=command_id,
        machine_id=machine.machine_id,
        expected_revision=revision,
        kind=kind,
        payload=payload,
    )


def test_runtime_event_rule_executes_through_machine_journal() -> None:
    rules = ProgramRuleSet((
        ProgramRule(
            rule_id="model-complete",
            event_kind="model.completed",
            semantic=RuntimeConcern.TURN.value,
            operation="paper.accept-model",
            payload_matches={"role": "solver"},
        ),
    ))
    program = compile_rule_program(
        kind=MachineKind.RUNTIME,
        program_id="paper.runtime",
        version="1",
        state_schema="paper.runtime.state.v1",
        rules=rules,
    )
    downstream = ProgramHandlerRegistry()

    def accept_model(request):
        count = request.data.get("model_count", 0)
        return ProgramNodeResult(
            value={"accepted": True},
            state_update={"model_count": count + 1},
            events=({"type": "paper_model_accepted"},),
        )

    downstream.register(
        "paper.accept-model",
        accept_model,
        implementation_digest=canonical_digest({
            "operation": "paper.accept-model",
            "implementation_revision": 1,
        }),
    )
    interpreter = ProgrammableMachineInterpreter(
        program,
        build_rule_handlers(rules, downstream),
    )
    machine = _machine(program)
    machine.open({})
    machine.step(
        _command(machine, 0, "start", "program.start", {"initial_data": {"model_count": 0}}),
        interpreter,
    )
    commit = machine.step(
        _command(
            machine,
            1,
            "event:1",
            "program.step",
            {"event": MachineEvent("model.completed", {"role": "solver"}).as_payload()},
        ),
        interpreter,
    )
    state = thaw_json(commit.state)["_program"]
    assert state["data"]["model_count"] == 1
    assert state["status"] == "runnable"
    assert commit.event_payloads[0]["type"] == "research_program_node_executed"
    assert commit.event_payloads[1]["type"] == "program_event_dispatched"
    assert commit.event_payloads[1]["rule_ids"] == ("model-complete",)


def test_runtime_all_mode_is_deterministic_and_sequential() -> None:
    rules = ProgramRuleSet(
        (
            ProgramRule(
                rule_id="later",
                event_kind="message.received",
                semantic=RuntimeConcern.COMMUNICATION.value,
                operation="paper.second",
                priority=10,
            ),
            ProgramRule(
                rule_id="first",
                event_kind="message.received",
                semantic=RuntimeConcern.CONTEXT.value,
                operation="paper.first",
                priority=20,
            ),
        ),
        mode=RuleDispatchMode.ALL,
    )
    downstream = ProgramHandlerRegistry()

    def first(request):
        return ProgramNodeResult(state_update={"trace": ("first",)})

    def second(request):
        assert request.data["trace"] == ("first",)
        return ProgramNodeResult(state_update={"trace": ("first", "second")})

    downstream.register(
        "paper.first",
        first,
        implementation_digest=canonical_digest({
            "operation": "paper.first",
            "implementation_revision": 1,
        }),
    )
    downstream.register(
        "paper.second",
        second,
        implementation_digest=canonical_digest({
            "operation": "paper.second",
            "implementation_revision": 1,
        }),
    )
    program = compile_rule_program(
        kind=MachineKind.RUNTIME,
        program_id="paper.multi-rule-runtime",
        version="1",
        state_schema="paper.multi-rule-runtime.state.v1",
        rules=rules,
    )
    interpreter = ProgrammableMachineInterpreter(program, build_rule_handlers(rules, downstream))
    machine = _machine(program)
    machine.open({})
    machine.step(_command(machine, 0, "start", "program.start", {"initial_data": {}}), interpreter)
    commit = machine.step(
        _command(
            machine,
            1,
            "message",
            "program.step",
            {"event": MachineEvent("message.received", {"text": "hello"}).as_payload()},
        ),
        interpreter,
    )
    state = thaw_json(commit.state)["_program"]["data"]
    assert state["trace"] == ["first", "second"]
    assert commit.event_payloads[1]["rule_ids"] == ("first", "later")


def test_runtime_rule_guards_support_nested_state_and_payload_paths() -> None:
    rules = ProgramRuleSet((
        ProgramRule(
            rule_id="private-tool",
            event_kind="tool.requested",
            semantic=RuntimeConcern.CAPABILITY_MEDIATION.value,
            operation="paper.private-tool",
            state_matches={"visibility.mode": "private"},
            payload_matches={"tool.kind": "shell"},
        ),
    ))
    event = MachineEvent("tool.requested", {"tool": {"kind": "shell"}})
    assert tuple(rule.rule_id for rule in rules.ordered_matches(
        event,
        {"visibility": {"mode": "private"}},
    )) == ("private-tool",)
    assert not rules.ordered_matches(event, {"visibility": {"mode": "public"}})


def test_runtime_unhandled_wait_is_explicit_machine_wait_state() -> None:
    rules = ProgramRuleSet(
        (
            ProgramRule(
                rule_id="known",
                event_kind="known",
                semantic=RuntimeConcern.EVENT.value,
                operation="paper.known",
            ),
        ),
        unhandled=UnhandledEventPolicy.WAIT,
    )
    downstream = ProgramHandlerRegistry()
    downstream.register(
        "paper.known",
        lambda request: ProgramNodeResult(),
        implementation_digest=canonical_digest({
            "operation": "paper.known",
            "implementation_revision": 1,
        }),
    )
    program = compile_rule_program(
        kind=MachineKind.RUNTIME,
        program_id="paper.wait-runtime",
        version="1",
        state_schema="paper.wait-runtime.state.v1",
        rules=rules,
    )
    machine = _machine(program)
    interpreter = ProgrammableMachineInterpreter(program, build_rule_handlers(rules, downstream))
    machine.open({})
    machine.step(_command(machine, 0, "start", "program.start", {"initial_data": {}}), interpreter)
    commit = machine.step(
        _command(
            machine,
            1,
            "unknown",
            "program.step",
            {"event": MachineEvent("unknown", {}).as_payload()},
        ),
        interpreter,
    )
    assert commit.accepted_status.value == "waiting"
    assert commit.event_payloads[1]["policy"] == "wait"


def test_rule_set_is_part_of_runtime_program_identity() -> None:
    left = ProgramRuleSet((
        ProgramRule("rule", "event.a", "paper.a", semantic=RuntimeConcern.EVENT.value),
    ))
    right = ProgramRuleSet((
        ProgramRule("rule", "event.b", "paper.a", semantic=RuntimeConcern.EVENT.value),
    ))
    left_program = compile_rule_program(
        kind=MachineKind.RUNTIME,
        program_id="identity.runtime",
        version="1",
        state_schema="identity.runtime.state.v1",
        rules=left,
    )
    right_program = compile_rule_program(
        kind=MachineKind.RUNTIME,
        program_id="identity.runtime",
        version="1",
        state_schema="identity.runtime.state.v1",
        rules=right,
    )
    assert left.rule_set_digest != right.rule_set_digest
    assert left_program.program_digest != right_program.program_digest
