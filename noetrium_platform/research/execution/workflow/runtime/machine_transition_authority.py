"""Machine-Journal authority for node-level MethodProgram transitions.

Operation/effect execution happens before this seam.  This module only commits
an already-resolved Method transition into the shared Machine Journal, making
Machine the single durable execution truth while UMM remains the interpreter.
"""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    MachineCommand,
    MachineKind,
    MachineExecutor,
    MachineSnapshot,
    MachineStatus,
    TransitionProposal,
    JsonObject,
    JsonValue,
    canonical_digest,
    thaw_json,
)

from ..api.method_machine import (
    MethodAuthoritativeState,
    MethodCheckpoint,
    MethodControlRecord,
    MethodEvent,
    MethodProgram,
    MethodTransitionRecord,
)


def _method_state_document(state: MethodAuthoritativeState) -> JsonObject:
    return {
        "run_id": state.run_id,
        "program_digest": state.program_digest,
        "sequence": state.sequence,
        "current_node": state.current_node,
        "state": thaw_json(state.state),
        "previous_value": thaw_json(state.previous_value),
        "visit_counts": [[node, count] for node, count in state.visit_counts],
        "checkpoint_value": thaw_json(state.checkpoint_value),
        "binding_plan_digest": state.binding_plan_digest,
        "runtime_binding_digest": state.runtime_binding_digest,
        "schema_digest": state.schema_digest,
    }


def _effect_document(receipt: EffectReceipt) -> JsonObject:
    return {
        "effect_id": receipt.effect_id,
        "request_digest": receipt.request_digest,
        "effect_class": receipt.effect_class.value,
        "certainty": receipt.certainty.value,
        "provider_instance_id": receipt.provider_instance_id,
        "verification_required": receipt.verification_required,
        "before_artifact": receipt.before_artifact,
        "after_artifact": receipt.after_artifact,
        "provider_receipt": receipt.provider_receipt,
    }


def _require_text(value: JsonValue, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _optional_text(value: JsonValue, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field)


def _decode_effect(value: Mapping[str, JsonValue]) -> EffectReceipt:
    expected = {
        "effect_id", "request_digest", "effect_class", "certainty",
        "provider_instance_id", "verification_required", "before_artifact",
        "after_artifact", "provider_receipt",
    }
    if set(value) != expected:
        raise ValueError("method effect receipt payload fields are not exact")
    verification = value["verification_required"]
    if not isinstance(verification, bool):
        raise TypeError("method effect receipt verification_required must be boolean")
    return EffectReceipt(
        effect_id=_require_text(value["effect_id"], "effect_id"),
        request_digest=_require_text(value["request_digest"], "request_digest"),
        effect_class=EffectClass(_require_text(value["effect_class"], "effect_class")),
        certainty=EffectCertainty(_require_text(value["certainty"], "certainty")),
        provider_instance_id=_optional_text(value["provider_instance_id"], "provider_instance_id"),
        verification_required=verification,
        before_artifact=_optional_text(value["before_artifact"], "before_artifact"),
        after_artifact=_optional_text(value["after_artifact"], "after_artifact"),
        provider_receipt=_optional_text(value["provider_receipt"], "provider_receipt"),
    )


def _state_from_document(
    value: Mapping[str, JsonValue],
    *,
    events: tuple[MethodEvent, ...] = (),
    effects: tuple[EffectReceipt, ...] = (),
) -> MethodAuthoritativeState:
    visit_rows = value.get("visit_counts", ())
    if not isinstance(visit_rows, (tuple, list)):
        raise TypeError("method machine visit_counts must be a sequence")
    visit_counts = tuple((str(row[0]), int(row[1])) for row in visit_rows)
    return MethodAuthoritativeState(
        run_id=str(value["run_id"]),
        program_digest=str(value["program_digest"]),
        sequence=int(value["sequence"]),
        current_node=str(value["current_node"]),
        state=value.get("state", {}),
        previous_value=value.get("previous_value"),
        visit_counts=visit_counts,
        events=events,
        effect_receipts=effects,
        checkpoint_value=value.get("checkpoint_value"),
        binding_plan_digest=value.get("binding_plan_digest") if isinstance(value.get("binding_plan_digest"), str) else None,
        runtime_binding_digest=value.get("runtime_binding_digest") if isinstance(value.get("runtime_binding_digest"), str) else None,
        schema_digest=value.get("schema_digest") if isinstance(value.get("schema_digest"), str) else None,
    )


class _ResolvedMethodTransitionInterpreter:
    """Pure projection of one already-resolved Method transition into Machine state."""

    def __init__(self, transition: MethodTransitionRecord) -> None:
        self._transition = transition

    def propose(self, command: MachineCommand, state: MachineSnapshot) -> TransitionProposal:
        transition = self._transition
        current = state.state.get("method") if isinstance(state.state, Mapping) else None
        if not isinstance(current, Mapping):
            raise RuntimeError("method machine state is missing canonical method state")
        if int(current.get("sequence", -1)) + 1 != transition.post_state.sequence:
            raise RuntimeError("method machine transition sequence is not monotonic")
        if current.get("current_node") != transition.executed_node:
            raise RuntimeError("method machine executed node does not match authoritative cursor")
        event_payloads = tuple(
            {
                "kind": "method.event",
                "event": {"kind": event.kind, "payload": thaw_json(event.payload)},
            }
            for event in transition.emitted_events
        )
        event_payloads += tuple(
            {"kind": "method.effect_receipt", "receipt": _effect_document(receipt)}
            for receipt in transition.emitted_effect_receipts
        )
        if transition.interrupt is not None:
            event_payloads += ({
                "kind": "method.interrupt",
                "interrupt_id": transition.interrupt.interrupt_id,
                "node_id": transition.interrupt.node_id,
                "payload": thaw_json(transition.interrupt.payload),
            },)
        event_payloads += ({
            "kind": "method.transition",
            "executed_node": transition.executed_node,
            "sequence": transition.post_state.sequence,
            "next_node": transition.post_state.current_node,
        },)
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta={"method": _method_state_document(transition.post_state)},
            event_payloads=event_payloads,
            effect_intent_refs=tuple(
                receipt.effect_id for receipt in transition.emitted_effect_receipts
            ),
            child_links=transition.emitted_child_links,
        )


class _MethodControlInterpreter:
    def __init__(self, record: MethodControlRecord) -> None:
        self._record = record

    def propose(self, command: MachineCommand, state: MachineSnapshot) -> TransitionProposal:
        record = self._record
        status_map = {
            "succeeded": MachineStatus.COMPLETED,
            "interrupted": MachineStatus.INTERRUPTED,
            "failed": MachineStatus.FAILED,
            "limit_reached": MachineStatus.INTERRUPTED,
        }
        accepted = status_map[record.status.value]
        event = {
            "kind": "method.control",
            "status": record.status.value,
            "sequence": record.state.sequence,
            "current_node": record.state.current_node,
            "failure": record.failure,
            "failure_code": record.failure_code,
            "failure_phase": record.failure_phase,
        }
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta={},
            event_payloads=(event,),
            accepted_status=accepted,
        )


class MachineMethodTransitionAuthority:
    """Bind Method transition truth to one METHOD MachineExecutor."""

    def __init__(self, machine: MachineExecutor) -> None:
        if not isinstance(machine, MachineExecutor):
            raise TypeError("method transition authority requires MachineExecutor")
        if machine.identity.kind is not MachineKind.METHOD:
            raise ValueError("method transition authority requires a METHOD machine")
        self._machine = machine

    @property
    def machine(self) -> MachineExecutor:
        return self._machine

    @property
    def machine_id(self) -> str:
        return self._machine.machine_id

    def _history_evidence(self) -> tuple[tuple[MethodEvent, ...], tuple[EffectReceipt, ...]]:
        events: list[MethodEvent] = []
        effects: list[EffectReceipt] = []
        for commit in self._machine.journal.commits(self._machine.machine_id):
            for payload in commit.event_payloads:
                if not isinstance(payload, Mapping):
                    continue
                kind = payload.get("kind")
                if kind == "method.event":
                    event = payload.get("event")
                    if isinstance(event, Mapping) and isinstance(event.get("kind"), str):
                        events.append(MethodEvent(str(event["kind"]), event.get("payload")))
                elif kind == "method.effect_receipt":
                    receipt = payload.get("receipt")
                    if isinstance(receipt, Mapping):
                        effects.append(_decode_effect(receipt))
        return tuple(events), tuple(effects)

    def _materialize(self, snapshot: MachineSnapshot) -> MethodAuthoritativeState:
        method = snapshot.state.get("method") if isinstance(snapshot.state, Mapping) else None
        if not isinstance(method, Mapping):
            raise RuntimeError("machine snapshot is missing method state")
        events, effects = self._history_evidence()
        return _state_from_document(method, events=events, effects=effects)

    @staticmethod
    def _binding_tuple(state: MethodAuthoritativeState) -> tuple[str | None, str | None, str | None]:
        return state.binding_plan_digest, state.runtime_binding_digest, state.schema_digest

    def open(
        self,
        *,
        run_id: str,
        program: MethodProgram,
        initial_state,
        resume: bool,
        binding_plan_digest: str | None = None,
        runtime_binding_digest: str | None = None,
        schema_digest: str | None = None,
    ) -> MethodAuthoritativeState:
        if self._machine.program.program_digest != program.program_digest:
            raise ValueError("METHOD machine program digest does not match MethodProgram")
        latest = self._machine.journal.latest(self._machine.machine_id)
        if latest is not None and latest.program_digest not in (None, program.program_digest):
            raise ValueError("METHOD machine journal belongs to another program")
        initial = MethodAuthoritativeState(
            run_id=run_id,
            program_digest=program.program_digest,
            sequence=0,
            current_node=program.graph.entrypoint,
            state=initial_state,
            binding_plan_digest=binding_plan_digest,
            runtime_binding_digest=runtime_binding_digest,
            schema_digest=schema_digest,
        )
        snapshot = self._machine.open({"method": _method_state_document(initial)})
        accepted = self._materialize(snapshot)
        if accepted.run_id != run_id or accepted.program_digest != program.program_digest:
            raise ValueError("METHOD machine state identity drift")
        if self._binding_tuple(accepted) != self._binding_tuple(initial):
            raise ValueError("METHOD machine runtime binding drift")
        if snapshot.revision > 0 and not resume:
            raise ValueError("METHOD machine already has committed transitions; resume is required")
        return accepted

    def commit(self, transition: MethodTransitionRecord) -> MethodAuthoritativeState:
        if not isinstance(transition, MethodTransitionRecord):
            raise TypeError("method transition authority accepts MethodTransitionRecord")
        current_snapshot = self._machine.open()
        current = self._materialize(current_snapshot)
        post = transition.post_state
        if post.run_id != current.run_id or post.program_digest != current.program_digest:
            raise ValueError("method transition identity drift")
        if post.sequence != current.sequence + 1:
            raise ValueError("method transition sequence must advance exactly once")
        if transition.executed_node != current.current_node:
            raise ValueError("method transition executed node does not match current cursor")
        if self._binding_tuple(post) != self._binding_tuple(current):
            raise ValueError("method transition runtime binding drift")
        payload = {
            "program_digest": post.program_digest,
            "sequence": post.sequence,
            "executed_node": transition.executed_node,
            "next_node": post.current_node,
            "post_state_digest": canonical_digest(_method_state_document(post)),
            "event_digests": [canonical_digest({"kind": event.kind, "payload": event.payload}) for event in transition.emitted_events],
            "effect_ids": [receipt.effect_id for receipt in transition.emitted_effect_receipts],
            "child_link_digests": [
                link.link_digest for link in transition.emitted_child_links
            ],
            "interrupt_id": None if transition.interrupt is None else transition.interrupt.interrupt_id,
        }
        command = MachineCommand(
            command_id=f"method:{post.run_id}:{post.sequence}:{transition.executed_node}",
            machine_id=self._machine.machine_id,
            expected_revision=current_snapshot.revision,
            kind="method.node",
            payload=payload,
            idempotency_key=f"method:{post.program_digest}:{post.sequence}:{transition.executed_node}",
        )
        accepted = self._machine.step(command, _ResolvedMethodTransitionInterpreter(transition))
        return self._materialize(MachineSnapshot(
            machine_id=self._machine.machine_id,
            revision=accepted.revision,
            program=self._machine.program,
            state=accepted.state,
            parent_commit_id=accepted.commit_id,
        ))


    def commit_control(self, record: MethodControlRecord) -> MethodAuthoritativeState:
        if not isinstance(record, MethodControlRecord):
            raise TypeError("method transition authority accepts MethodControlRecord")
        snapshot = self._machine.open()
        current = self._materialize(snapshot)
        if record.state.run_id != current.run_id or record.state.program_digest != current.program_digest:
            raise ValueError("method control identity drift")
        if record.state.sequence != current.sequence or record.state.current_node != current.current_node:
            raise ValueError("method control state is stale")
        if self._binding_tuple(record.state) != self._binding_tuple(current):
            raise ValueError("method control runtime binding drift")
        next_revision = snapshot.revision + 1
        command = MachineCommand(
            command_id=f"method:{current.run_id}:control:{next_revision}:{record.status.value}",
            machine_id=self._machine.machine_id,
            expected_revision=snapshot.revision,
            kind="method.control",
            payload={
                "status": record.status.value,
                "sequence": current.sequence,
                "current_node": current.current_node,
                "failure_code": record.failure_code,
                "failure_phase": record.failure_phase,
            },
        )
        accepted = self._machine.step(command, _MethodControlInterpreter(record))
        return self._materialize(MachineSnapshot(
            machine_id=self._machine.machine_id,
            revision=accepted.revision,
            program=self._machine.program,
            state=accepted.state,
            parent_commit_id=accepted.commit_id,
        ))

    def checkpoint(self, state: MethodAuthoritativeState) -> MethodCheckpoint:
        if not isinstance(state, MethodAuthoritativeState):
            raise TypeError("method checkpoint requires MethodAuthoritativeState")
        snapshot = self._machine.open()
        current = self._materialize(snapshot)
        if state.run_id != current.run_id or state.program_digest != current.program_digest:
            raise ValueError("method checkpoint identity drift")
        if state.sequence != current.sequence or state.current_node != current.current_node:
            raise ValueError("method checkpoint state is stale")
        if self._binding_tuple(state) != self._binding_tuple(current):
            raise ValueError("method checkpoint runtime binding drift")
        snap = self._machine.checkpoint()
        return MethodCheckpoint(
            run_id=current.run_id,
            program_digest=current.program_digest,
            sequence=current.sequence,
            current_node=current.current_node,
            machine_id=snap.machine_id,
            machine_revision=snap.revision,
            machine_commit_id=snap.parent_commit_id,
            state_digest=canonical_digest(snap.state),
            checkpoint_value=current.checkpoint_value,
        )


__all__ = ["MachineMethodTransitionAuthority"]
