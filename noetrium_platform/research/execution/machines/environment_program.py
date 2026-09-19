"""Programmable Environment Machine semantics for closed-world dynamics.

Environment providers own external I/O. Scientific environment state,
action identity, observations, reconciliation and branchable state are
journal-backed Machine facts. Downstream work may replace rules/handlers or
inject arbitrary deterministic dynamics without creating a new runner.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionRequest,
    StateMachineDynamicsPort,
    StateTransition,
    action_request_digest,
)
from noetrium_platform.capabilities.environment.api.state_machine import (
    freeze_json_mapping,
    thaw_json_mapping,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    ExecutionContext,
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from .domains import EnvironmentConcern
from .program_host import ResearchProgramHost
from .program import (
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchProgram,
)
from .rule_program import (
    ProgramRule,
    ProgramRuleSet,
    RuleDispatchMode,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
)


@dataclass(frozen=True, slots=True)
class EnvironmentMachineSpec:
    environment_id: str
    session_id: str
    generation: str
    provider_instance_id: str
    action_types: tuple[str, ...]
    initial_state: JsonObject
    state_schema_id: str = "environment.state.v1"
    spec_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("environment_id", self.environment_id),
            ("session_id", self.session_id),
            ("generation", self.generation),
            ("provider_instance_id", self.provider_instance_id),
            ("state_schema_id", self.state_schema_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"environment machine {name} is required")
        if type(self.action_types) is not tuple or not self.action_types:
            raise ValueError("environment machine action_types must be a non-empty tuple")
        if any(type(value) is not str or not value.strip() for value in self.action_types):
            raise ValueError("environment machine action_types must contain non-empty strings")
        if len(self.action_types) != len(set(self.action_types)):
            raise ValueError("environment machine action_types must be unique")
        if not isinstance(self.initial_state, Mapping):
            raise TypeError("environment machine initial_state must be an object")
        object.__setattr__(self, "initial_state", freeze_json(self.initial_state))
        object.__setattr__(self, "spec_digest", canonical_digest({
            "environment_id": self.environment_id,
            "session_id": self.session_id,
            "generation": self.generation,
            "provider_instance_id": self.provider_instance_id,
            "action_types": self.action_types,
            "initial_state": self.initial_state,
            "state_schema_id": self.state_schema_id,
        }))


def environment_rule_set() -> ProgramRuleSet:
    return ProgramRuleSet(
        (
            ProgramRule(
                "observe",
                "environment.observe",
                "environment.default.observe",
                priority=100,
                semantic=EnvironmentConcern.OBSERVATION.value,
            ),
            ProgramRule(
                "act",
                "environment.act",
                "environment.default.act",
                priority=100,
                semantic=EnvironmentConcern.TRANSITION.value,
            ),
            ProgramRule(
                "query",
                "environment.query",
                "environment.default.query",
                priority=100,
                semantic=EnvironmentConcern.QUERY.value,
            ),
            ProgramRule(
                "reconcile",
                "environment.reconcile",
                "environment.default.reconcile",
                priority=100,
                semantic=EnvironmentConcern.RECONCILIATION.value,
            ),
            ProgramRule(
                "branch-capture",
                "environment.branch.capture",
                "environment.default.branch-capture",
                priority=100,
                semantic=EnvironmentConcern.BRANCHING.value,
            ),
            ProgramRule(
                "branch-restore",
                "environment.branch.restore",
                "environment.default.branch-restore",
                priority=100,
                semantic=EnvironmentConcern.BRANCHING.value,
            ),
            ProgramRule(
                "snapshot-restore",
                "environment.snapshot.restore",
                "environment.default.snapshot-restore",
                priority=100,
                semantic=EnvironmentConcern.RECOVERY.value,
            ),
            ProgramRule(
                "reset",
                "environment.reset",
                "environment.default.reset",
                priority=100,
                semantic=EnvironmentConcern.RESET.value,
            ),
            ProgramRule(
                "close",
                "environment.close",
                "environment.default.close",
                priority=100,
                semantic=EnvironmentConcern.RECOVERY.value,
            ),
        ),
        mode=RuleDispatchMode.FIRST,
        unhandled=UnhandledEventPolicy.ERROR,
    )


def compile_environment_program(
    *,
    program_id: str = "environment.closed-world.default",
    version: str = "1",
    rules: ProgramRuleSet | None = None,
) -> ResearchProgram:
    selected = environment_rule_set() if rules is None else rules
    return compile_rule_program(
        program_id=program_id,
        kind=MachineKind.ENVIRONMENT,
        version=version,
        state_schema="environment.program.state.v1",
        rules=selected,
    )


def environment_initial_data(spec: EnvironmentMachineSpec) -> JsonObject:
    if not isinstance(spec, EnvironmentMachineSpec):
        raise TypeError("environment initial data requires EnvironmentMachineSpec")
    return {
        "environment_spec_digest": spec.spec_digest,
        "environment_id": spec.environment_id,
        "session_id": spec.session_id,
        "generation": spec.generation,
        "provider_instance_id": spec.provider_instance_id,
        "state_schema_id": spec.state_schema_id,
        "action_types": spec.action_types,
        "initial_state": spec.initial_state,
        "state": spec.initial_state,
        "state_digest": canonical_digest(spec.initial_state),
        "observation_sequence": 0,
        "actions": {},
        "closed": False,
    }


_CONTEXT_FIELDS = (
    "run_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "study_id",
    "condition_id",
    "lifetime_id",
    "branch_id",
    "task_id",
    "decision_cycle_id",
    "checkpoint_id",
    "operation_id",
    "component_id",
    "participant_generations",
    "platform_generation",
)


def execution_context_payload(context: ExecutionContext) -> JsonObject:
    if not isinstance(context, ExecutionContext):
        raise TypeError("environment context must be ExecutionContext")
    return {
        field_name: getattr(context, field_name)
        for field_name in _CONTEXT_FIELDS
    }


def execution_context_from_payload(value: JsonObject) -> ExecutionContext:
    if not isinstance(value, Mapping):
        raise TypeError("environment context payload must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("environment context payload must decode to an object")
    unknown = set(decoded) - set(_CONTEXT_FIELDS)
    if unknown:
        raise ValueError(f"environment context payload has unknown fields: {sorted(unknown)}")
    generations = decoded.get("participant_generations", ())
    if not isinstance(generations, (tuple, list)):
        raise TypeError("participant_generations must be a sequence")
    decoded["participant_generations"] = tuple(tuple(row) for row in generations)
    return ExecutionContext(**decoded)


def _data(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("environment program data must be an object")
    return value


def _payload(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    value = thaw_json(request.payload)
    if not isinstance(value, dict):
        raise TypeError("environment event payload must be an object")
    return value


def _assert_open(data: dict[str, JsonValue]) -> None:
    if data.get("closed") is True:
        raise RuntimeError("environment machine is closed")


def _next_observation(
    data: dict[str, JsonValue],
    *,
    kind: str,
    extra: JsonObject | None = None,
    artifact_refs: tuple[str, ...] = (),
) -> tuple[JsonObject, int]:
    sequence = data.get("observation_sequence", 0)
    if type(sequence) is not int or sequence < 0:
        raise ValueError("environment observation_sequence is invalid")
    sequence += 1
    state = data.get("state")
    if not isinstance(state, Mapping):
        raise TypeError("environment state must be an object")
    generation = data.get("generation")
    environment_id = data.get("environment_id")
    session_id = data.get("session_id")
    if (
        type(generation) is not str
        or type(environment_id) is not str
        or type(session_id) is not str
    ):
        raise TypeError("environment identity state is invalid")
    payload: dict[str, JsonValue] = {
        "kind": kind,
        "state": state,
        "state_digest": canonical_digest(state),
    }
    if extra is not None:
        payload.update(dict(extra))
    observation: JsonObject = {
        "observation_id": f"state-machine:{session_id}:observation:{sequence}",
        "generation": generation,
        "payload": payload,
        "artifact_refs": artifact_refs,
    }
    return observation, sequence


def _effect_payload(
    *,
    action_id: str,
    request_digest: str,
    accepted: bool,
    provider_instance_id: str,
    state_digest: str,
) -> JsonObject:
    return {
        "effect_id": f"state-machine-action:{action_id}",
        "request_digest": request_digest,
        "effect_class": EffectClass.IDEMPOTENT.value,
        "certainty": (
            EffectCertainty.EFFECT_CONFIRMED.value
            if accepted
            else EffectCertainty.EFFECT_REJECTED.value
        ),
        "provider_instance_id": provider_instance_id,
        "verification_required": False,
        "before_artifact": None,
        "after_artifact": state_digest,
        "provider_receipt": action_id,
    }


def state_machine_environment_operations(
    dynamics: StateMachineDynamicsPort,
) -> ProgramHandlerRegistry:
    if not isinstance(dynamics, StateMachineDynamicsPort):
        raise TypeError("environment program requires StateMachineDynamicsPort")

    operations = ProgramHandlerRegistry()

    def observe(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        _assert_open(data)
        observation, sequence = _next_observation(
            data,
            kind="state_machine_snapshot",
        )
        return ProgramNodeResult(
            value={"observation": observation},
            state_update={"observation_sequence": sequence},
            events=({
                "type": "environment_observed",
                "observation_id": observation["observation_id"],
                "state_digest": observation["payload"]["state_digest"],
            },),
        )

    def query(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        _assert_open(data)
        query_type = payload.get("query_type")
        query_id = payload.get("query_id")
        if type(query_type) is not str or not query_type.strip():
            raise ValueError("environment query_type is required")
        if type(query_id) is not str or not query_id.strip():
            raise ValueError("environment query_id is required")
        if query_type == "state":
            result: JsonObject = {
                "state": data["state"],
                "state_digest": data["state_digest"],
                "generation": data["generation"],
            }
        elif query_type == "capabilities":
            result = {
                "action_types": data["action_types"],
                "query_types": ("state", "capabilities"),
            }
        else:
            raise ValueError(f"unsupported environment query: {query_type}")
        observation, sequence = _next_observation(
            data,
            kind=f"query:{query_type}",
        )
        return ProgramNodeResult(
            value={
                "query_id": query_id,
                "accepted": True,
                "payload": result,
                "observation": observation,
            },
            state_update={"observation_sequence": sequence},
            events=({
                "type": "environment_query_completed",
                "query_id": query_id,
                "query_type": query_type,
            },),
        )

    def act(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        _assert_open(data)
        action_id = payload.get("action_id")
        action_type = payload.get("action_type")
        action_payload = payload.get("payload")
        context_payload = payload.get("context")
        if type(action_id) is not str or not action_id.strip():
            raise ValueError("environment action_id is required")
        if type(action_type) is not str or not action_type.strip():
            raise ValueError("environment action_type is required")
        if action_type not in tuple(data.get("action_types", ())):
            raise ValueError(f"unsupported environment action type: {action_type}")
        if not isinstance(action_payload, Mapping):
            raise TypeError("environment action payload must be an object")
        if not isinstance(context_payload, Mapping):
            raise TypeError("environment action context must be an object")
        context = execution_context_from_payload(context_payload)
        action_request = ActionRequest(action_id, action_type, action_payload, context)
        request_digest = action_request_digest(action_request)

        actions_value = data.get("actions", {})
        if not isinstance(actions_value, Mapping):
            raise TypeError("environment action ledger must be an object")
        actions = dict(actions_value)
        prior = actions.get(action_id)
        if prior is not None:
            if not isinstance(prior, Mapping):
                raise TypeError("environment action ledger row must be an object")
            if prior.get("request_digest") != request_digest:
                raise ActionIdentityViolation(
                    f"environment action identity was reused with drift: {action_id}"
                )
            result = prior.get("result")
            if not isinstance(result, Mapping):
                raise TypeError("environment action ledger result must be an object")
            return ProgramNodeResult(
                value={"action_result": result, "replayed": True},
                events=({
                    "type": "environment_action_replayed",
                    "action_id": action_id,
                    "request_digest": request_digest,
                },),
            )

        state_value = data.get("state")
        if not isinstance(state_value, Mapping):
            raise TypeError("environment state must be an object")
        transition = dynamics.transition(state_value, action_request, context)
        if not isinstance(transition, StateTransition):
            raise TypeError("environment dynamics returned invalid StateTransition")
        next_state = freeze_json_mapping(transition.state, field="transition.state")
        before_digest = canonical_digest(state_value)
        after_digest = canonical_digest(next_state)
        if not transition.accepted and after_digest != before_digest:
            raise ValueError("a rejected environment transition cannot mutate state")
        provider_instance_id = data.get("provider_instance_id")
        if type(provider_instance_id) is not str:
            raise TypeError("environment provider_instance_id is invalid")
        extra: JsonObject = {
            "action": {
                "action_id": action_id,
                "action_type": action_type,
                "payload": action_payload,
            },
            "accepted": transition.accepted,
            "transition_diagnostics": transition.diagnostics,
        }
        next_data = dict(data)
        next_data["state"] = next_state
        next_data["state_digest"] = after_digest
        observation, sequence = _next_observation(
            next_data,
            kind="state_machine_transition",
            extra=extra,
            artifact_refs=transition.artifact_refs,
        )
        effect = _effect_payload(
            action_id=action_id,
            request_digest=request_digest,
            accepted=transition.accepted,
            provider_instance_id=provider_instance_id,
            state_digest=after_digest,
        )
        result: JsonObject = {
            "action_id": action_id,
            "accepted": transition.accepted,
            "observation": observation,
            "effect": effect,
            "diagnostics": {
                "environment": "state_machine",
                "verified": True,
                "state_digest": after_digest,
                **thaw_json_mapping(transition.diagnostics),
            },
        }
        actions[action_id] = {
            "request_digest": request_digest,
            "result": result,
        }
        return ProgramNodeResult(
            value={"action_result": result, "replayed": False},
            state_update={
                "state": next_state,
                "state_digest": after_digest,
                "observation_sequence": sequence,
                "actions": actions,
            },
            events=({
                "type": "environment_action_applied",
                "action_id": action_id,
                "request_digest": request_digest,
                "accepted": transition.accepted,
                "before_state_digest": before_digest,
                "after_state_digest": after_digest,
            },),
            artifact_refs=transition.artifact_refs,
        )

    def reconcile(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        _assert_open(data)
        action_id = payload.get("action_id")
        request_digest = payload.get("request_digest")
        if type(action_id) is not str or not action_id.strip():
            raise ValueError("environment reconcile action_id is required")
        if type(request_digest) is not str or not request_digest.strip():
            raise ValueError("environment reconcile request_digest is required")
        actions_value = data.get("actions", {})
        if not isinstance(actions_value, Mapping):
            raise TypeError("environment action ledger must be an object")
        row = actions_value.get(action_id)
        if not isinstance(row, Mapping):
            raise ActionIdentityViolation(
                "environment effect does not identify an applied action"
            )
        if row.get("request_digest") != request_digest:
            raise ActionIdentityViolation(
                "environment reconcile request digest does not match action ledger"
            )
        result = row.get("result")
        if not isinstance(result, Mapping):
            raise TypeError("environment action ledger result must be an object")
        effect = result.get("effect")
        if not isinstance(effect, Mapping):
            raise RuntimeError("environment action ledger has no effect receipt")
        return ProgramNodeResult(
            value={"effect": effect},
            events=({
                "type": "environment_effect_reconciled",
                "action_id": action_id,
                "request_digest": request_digest,
            },),
        )

    def branch_capture(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        _assert_open(data)
        return ProgramNodeResult(
            value={
                "state_schema_id": data["state_schema_id"],
                "state": data["state"],
                "state_digest": data["state_digest"],
                "generation": data["generation"],
            },
            events=({
                "type": "environment_branch_captured",
                "state_digest": data["state_digest"],
            },),
        )

    def branch_restore(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        _assert_open(data)
        state = payload.get("state")
        state_digest = payload.get("state_digest")
        if not isinstance(state, Mapping):
            raise TypeError("environment branch restore state must be an object")
        if type(state_digest) is not str or not state_digest.strip():
            raise ValueError("environment branch restore state_digest is required")
        frozen = freeze_json_mapping(state, field="branch_state.state")
        if canonical_digest(frozen) != state_digest:
            raise ValueError("environment branch restore state digest mismatch")
        return ProgramNodeResult(
            value={"state_digest": state_digest},
            state_update={
                "state": frozen,
                "state_digest": state_digest,
                "observation_sequence": 0,
                "actions": {},
            },
            events=({
                "type": "environment_branch_restored",
                "state_digest": state_digest,
            },),
        )


    def snapshot_restore(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        _assert_open(data)
        state = payload.get("state")
        state_digest = payload.get("state_digest")
        observation_sequence = payload.get("observation_sequence")
        actions = payload.get("actions")
        if not isinstance(state, Mapping):
            raise TypeError("environment snapshot state must be an object")
        if type(state_digest) is not str or not state_digest.strip():
            raise ValueError("environment snapshot state_digest is required")
        if type(observation_sequence) is not int or observation_sequence < 0:
            raise ValueError("environment snapshot observation_sequence is invalid")
        if not isinstance(actions, Mapping):
            raise TypeError("environment snapshot actions must be an object")
        frozen = freeze_json_mapping(state, field="snapshot.state")
        if canonical_digest(frozen) != state_digest:
            raise ValueError("environment snapshot state digest mismatch")
        return ProgramNodeResult(
            value={
                "state_digest": state_digest,
                "observation_sequence": observation_sequence,
            },
            state_update={
                "state": frozen,
                "state_digest": state_digest,
                "observation_sequence": observation_sequence,
                "actions": dict(actions),
            },
            events=({
                "type": "environment_snapshot_restored",
                "state_digest": state_digest,
                "observation_sequence": observation_sequence,
            },),
        )

    def reset(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        _assert_open(data)
        initial_state = data.get("initial_state")
        if not isinstance(initial_state, Mapping):
            raise TypeError("environment initial state must be an object")
        digest = canonical_digest(initial_state)
        return ProgramNodeResult(
            value={"state_digest": digest},
            state_update={
                "state": initial_state,
                "state_digest": digest,
                "observation_sequence": 0,
                "actions": {},
            },
            events=({
                "type": "environment_reset",
                "state_digest": digest,
            },),
        )

    def close(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        if data.get("closed") is True:
            raise RuntimeError("environment machine is already closed")
        return ProgramNodeResult(
            value={"closed": True},
            state_update={"closed": True},
            status=MachineStatus.COMPLETED,
            events=({"type": "environment_closed"},),
        )

    operations.register(
        "environment.default.observe",
        observe,
        implementation_digest=canonical_digest({
            "operation": "environment.default.observe",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.query",
        query,
        implementation_digest=canonical_digest({
            "operation": "environment.default.query",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.act",
        act,
        implementation_digest=canonical_digest({
            "operation": "environment.default.act",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.reconcile",
        reconcile,
        implementation_digest=canonical_digest({
            "operation": "environment.default.reconcile",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.branch-capture",
        branch_capture,
        implementation_digest=canonical_digest({
            "operation": "environment.default.branch-capture",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.branch-restore",
        branch_restore,
        implementation_digest=canonical_digest({
            "operation": "environment.default.branch-restore",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.snapshot-restore",
        snapshot_restore,
        implementation_digest=canonical_digest({
            "operation": "environment.default.snapshot-restore",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.reset",
        reset,
        implementation_digest=canonical_digest({
            "operation": "environment.default.reset",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "environment.default.close",
        close,
        implementation_digest=canonical_digest({
            "operation": "environment.default.close",
            "implementation_revision": 1,
        }),
    )
    return operations


def state_machine_environment_handlers(
    dynamics: StateMachineDynamicsPort,
) -> ProgramHandlerRegistry:
    return build_rule_handlers(
        environment_rule_set(),
        state_machine_environment_operations(dynamics),
    )


def state_machine_environment_host(
    dynamics: StateMachineDynamicsPort,
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    """Host closed-world EnvironmentProgram semantics with injected dynamics."""
    if not isinstance(dynamics, StateMachineDynamicsPort):
        raise TypeError("environment host requires StateMachineDynamicsPort")
    program = compile_environment_program()
    return ResearchProgramHost(
        host_id="environment.closed-world.default",
        program=program,
        journal=journal,
        snapshot_store=snapshot_store,
        base_handlers=state_machine_environment_handlers(dynamics),
        dependency_identity={
            "rule_set_digest": environment_rule_set().rule_set_digest,
            "dynamics_identity": dynamics.identity,
        },
    )


__all__ = [
    "EnvironmentMachineSpec",
    "compile_environment_program",
    "environment_initial_data",
    "environment_rule_set",
    "execution_context_from_payload",
    "execution_context_payload",
    "state_machine_environment_handlers",
    "state_machine_environment_host",
    "state_machine_environment_operations",
]
