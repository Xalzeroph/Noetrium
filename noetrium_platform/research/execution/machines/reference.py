"""Reference interpreters for the domain Machine family.

These interpreters own only domain state semantics. They never write a
journal or call providers; MachineRuntime remains the sole commit authority.
"""

from __future__ import annotations

from typing import Any

from noetrium_platform.foundation.kernel.kernel import (
    MachineFamilyDescriptor,
    MachineKind,
    MachineSnapshot,
    TransitionProposal,
    thaw_json,
)


def _payload(command: Any) -> dict[str, Any]:
    value = thaw_json(command.payload)
    if not isinstance(value, dict):
        raise ValueError(f"{command.kind} payload must be an object")
    return value


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _mapping(state: MachineSnapshot, key: str) -> dict[str, Any]:
    value = thaw_json(state.state).get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"machine state field {key} must be an object")
    return dict(value)


def _list(state: MachineSnapshot, key: str) -> list[Any]:
    value = thaw_json(state.state).get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"machine state field {key} must be a list")
    return list(value)


class _ReferenceInterpreter:
    def _proposal(self, command: Any, state: MachineSnapshot,
                  delta: dict[str, Any],
                  event: dict[str, Any]) -> TransitionProposal:
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta=delta,
            event_payloads=(event,),
        )


class ExperimentMachineInterpreter(_ReferenceInterpreter):
    def propose(self, command: Any, state: MachineSnapshot) -> TransitionProposal:
        payload = _payload(command)
        trials = _mapping(state, "trials")
        if command.kind == "experiment.trial.define":
            trial_id = _text(payload.get("trial_id"), "trial_id")
            if trial_id in trials:
                raise ValueError("experiment trial already exists")
            trials[trial_id] = {
                "parameters": payload.get("parameters", {}),
                "status": "planned",
            }
            return self._proposal(command, state, {"trials": trials}, {
                "type": "trial_defined", "trial_id": trial_id,
            })
        if command.kind == "experiment.trial.complete":
            trial_id = _text(payload.get("trial_id"), "trial_id")
            if trial_id not in trials:
                raise KeyError(trial_id)
            trial = dict(trials[trial_id])
            trial.update({"status": "completed", "result": payload.get("result")})
            trials[trial_id] = trial
            return self._proposal(command, state, {"trials": trials}, {
                "type": "trial_completed", "trial_id": trial_id,
            })
        if command.kind == "experiment.finish":
            return self._proposal(command, state, {"status": "completed"}, {
                "type": "experiment_completed",
            })
        raise ValueError(f"unsupported experiment command: {command.kind}")


class RunLifecycleInterpreter(_ReferenceInterpreter):
    _statuses = {
        "run.start": "running",
        "run.pause": "paused",
        "run.resume": "running",
        "run.complete": "completed",
        "run.fail": "failed",
    }

    def propose(self, command: Any, state: MachineSnapshot) -> TransitionProposal:
        if command.kind not in self._statuses:
            raise ValueError(f"unsupported run command: {command.kind}")
        payload = _payload(command)
        status = self._statuses[command.kind]
        delta: dict[str, Any] = {"status": status}
        if command.kind in {"run.complete", "run.fail"}:
            delta["result"] = payload.get("result")
        return self._proposal(command, state, delta, {
            "type": "run_status_changed", "status": status,
        })


class AgentTurnMachineInterpreter(_ReferenceInterpreter):
    def propose(self, command: Any, state: MachineSnapshot) -> TransitionProposal:
        payload = _payload(command)
        turns = _list(state, "turns")
        turn_id = _text(payload.get("turn_id"), "turn_id")
        if any(isinstance(row, dict) and row.get("turn_id") == turn_id for row in turns):
            raise ValueError("agent turn already exists")
        turns.append({
            "turn_id": turn_id,
            "kind": command.kind,
            "input": payload.get("input"),
            "decision": payload.get("decision"),
        })
        return self._proposal(command, state, {"turns": turns}, {
            "type": "agent_turn_recorded", "turn_id": turn_id,
        })


class MemoryMachineInterpreter(_ReferenceInterpreter):
    def propose(self, command: Any, state: MachineSnapshot) -> TransitionProposal:
        payload = _payload(command)
        entries = _mapping(state, "entries")
        entry_id = _text(payload.get("entry_id"), "entry_id")
        if command.kind == "memory.write":
            if entry_id in entries:
                raise ValueError("memory entry already exists")
            entries[entry_id] = {
                "value": payload.get("value"),
                "status": "active",
                "provenance": payload.get("provenance"),
            }
        elif command.kind in {"memory.retract", "memory.promote"}:
            if entry_id not in entries:
                raise KeyError(entry_id)
            entry = dict(entries[entry_id])
            entry["status"] = "retracted" if command.kind == "memory.retract" else "promoted"
            entries[entry_id] = entry
        else:
            raise ValueError(f"unsupported memory command: {command.kind}")
        return self._proposal(command, state, {"entries": entries}, {
            "type": "memory_changed", "entry_id": entry_id,
        })


class EnvironmentMachineInterpreter(_ReferenceInterpreter):
    def propose(self, command: Any, state: MachineSnapshot) -> TransitionProposal:
        if command.kind not in {"environment.observe", "environment.action"}:
            raise ValueError(f"unsupported environment command: {command.kind}")
        payload = _payload(command)
        steps = _list(state, "steps")
        step_id = _text(payload.get("step_id"), "step_id")
        steps.append({
            "step_id": step_id,
            "kind": command.kind,
            "action": payload.get("action"),
            "observation": payload.get("observation"),
        })
        return self._proposal(command, state, {"steps": steps}, {
            "type": "environment_step_recorded", "step_id": step_id,
        })


class EvaluationMachineInterpreter(_ReferenceInterpreter):
    def propose(self, command: Any, state: MachineSnapshot) -> TransitionProposal:
        if command.kind not in {"evaluation.metric", "evaluation.complete"}:
            raise ValueError(f"unsupported evaluation command: {command.kind}")
        payload = _payload(command)
        metrics = _mapping(state, "metrics")
        if command.kind == "evaluation.metric":
            name = _text(payload.get("name"), "metric name")
            if name in metrics:
                raise ValueError("evaluation metric already exists")
            value = payload.get("value")
            if type(value) not in {int, float}:
                raise TypeError("evaluation metric value must be numeric")
            metrics[name] = {
                "value": value,
                "run_ids": payload.get("run_ids", []),
                "source_digest": payload.get("source_digest"),
            }
            delta = {"metrics": metrics}
        else:
            delta = {"metrics": metrics, "status": "completed"}
        return self._proposal(command, state, delta, {
            "type": "evaluation_updated", "kind": command.kind,
        })


def reference_machine_families() -> tuple[MachineFamilyDescriptor, ...]:
    """Return the explicit, testable VM family admission set."""

    return (
        MachineFamilyDescriptor(
            family_id="experiment.reference.v1",
            kind=MachineKind.EXPERIMENT,
            implementation_version="1",
            state_schema="experiment.state.v1",
            command_kinds=(
                "experiment.trial.define",
                "experiment.trial.complete",
                "experiment.finish",
            ),
        ),
        MachineFamilyDescriptor(
            family_id="run.lifecycle.v1",
            kind=MachineKind.RUN,
            implementation_version="1",
            state_schema="run.state.v1",
            command_kinds=("run.start", "run.pause", "run.resume",
                           "run.complete", "run.fail"),
        ),
        MachineFamilyDescriptor(
            family_id="agent.turn.v1",
            kind=MachineKind.AGENT,
            implementation_version="1",
            state_schema="agent.state.v1",
            command_kinds=("agent.turn.begin", "agent.decision", "agent.return"),
        ),
        MachineFamilyDescriptor(
            family_id="memory.evolution.v1",
            kind=MachineKind.MEMORY,
            implementation_version="1",
            state_schema="memory.state.v1",
            command_kinds=("memory.write", "memory.retract", "memory.promote"),
        ),
        MachineFamilyDescriptor(
            family_id="environment.session.v1",
            kind=MachineKind.ENVIRONMENT,
            implementation_version="1",
            state_schema="environment.state.v1",
            command_kinds=("environment.observe", "environment.action"),
        ),
        MachineFamilyDescriptor(
            family_id="evaluation.reference.v1",
            kind=MachineKind.EVALUATION,
            implementation_version="1",
            state_schema="evaluation.state.v1",
            command_kinds=("evaluation.metric", "evaluation.complete"),
        ),
    )


__all__ = [
    "AgentTurnMachineInterpreter",
    "EnvironmentMachineInterpreter",
    "EvaluationMachineInterpreter",
    "ExperimentMachineInterpreter",
    "MemoryMachineInterpreter",
    "RunLifecycleInterpreter",
    "reference_machine_families",
]