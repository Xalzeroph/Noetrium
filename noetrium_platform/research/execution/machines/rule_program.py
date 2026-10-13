"""Domain-neutral event/rule IR for programmable research Machines.

This module is a reusable semantic layer above NoetriumUnit. It lets any
research domain express event-driven transition selection without adding a
domain-specific runner or growing kernel enums.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.structure import structure_unit

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineStatus,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel.universal import (
    UnitOperationRegistry,
    UnitOperationRegistryPort,
    UnitGoto,
    UnitHalt,
    UnitSuspend,
    UnitStepContext,
    UnitTransition,
    unit_flow,
    executable_unit,
    unit_operation_required_capabilities,
    unit_operation,
)


class UnhandledEventPolicy(StrEnum):
    ERROR = "error"
    IGNORE = "ignore"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class MachineEvent:
    kind: str
    payload: JsonObject = field(default_factory=dict)
    source: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or not self.kind.strip():
            raise ValueError("machine event kind is required")
        if not isinstance(self.payload, Mapping):
            raise TypeError("machine event payload must be an object")
        if self.source is not None and (
            type(self.source) is not str or not self.source.strip()
        ):
            raise ValueError("machine event source must be non-empty when provided")
        object.__setattr__(self, "kind", self.kind.strip())
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def as_payload(self) -> JsonObject:
        return {
            "kind": self.kind,
            "payload": self.payload,
            "source": self.source,
        }

    @classmethod
    def from_payload(cls, value: object) -> "MachineEvent":
        if not isinstance(value, Mapping):
            raise TypeError("machine event envelope must be an object")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("machine event envelope must decode to an object")
        payload = decoded.get("payload", {})
        if not isinstance(payload, dict):
            raise TypeError("machine event payload must be an object")
        return cls(
            kind=decoded.get("kind"),
            payload=payload,
            source=decoded.get("source"),
        )


PROGRAM_RULE_TRAIT = "machine.rule"
PROGRAM_RULE_SET_TRAIT = "machine.rule-set"


def program_rule(
    rule_id: str,
    event_kind: str,
    operation: str,
    *,
    priority: int = 0,
    semantic: str | None = None,
    state_matches: Mapping[str, JsonValue] | None = None,
    payload_matches: Mapping[str, JsonValue] | None = None,
    configuration: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    for name, value in (
        ("rule_id", rule_id),
        ("event_kind", event_kind),
        ("operation", operation),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"program rule {name} is required")
    if type(priority) is not int:
        raise TypeError("program rule priority must be an integer")
    if semantic is not None and (
        type(semantic) is not str or not semantic.strip()
    ):
        raise ValueError("program rule semantic must be non-empty when provided")
    return structure_unit(
        rule_id.strip(),
        traits=(PROGRAM_RULE_TRAIT,),
        parameters={
            "event_kind": event_kind.strip(),
            "operation": operation.strip(),
            "priority": priority,
            "semantic": None if semantic is None else semantic.strip(),
            "state_matches": {} if state_matches is None else dict(state_matches),
            "payload_matches": {} if payload_matches is None else dict(payload_matches),
            "configuration": {} if configuration is None else dict(configuration),
        },
    )


def validate_program_rule(rule: NoetriumUnit) -> None:
    if type(rule) is not NoetriumUnit or not rule.has_trait(PROGRAM_RULE_TRAIT):
        raise TypeError("program rule must be machine.rule NoetriumUnit")
    params = rule.parameters
    for field in ("event_kind", "operation"):
        value = params.get(field)
        if type(value) is not str or not value.strip():
            raise ValueError(f"program rule {field} is required")
    if type(params.get("priority")) is not int:
        raise TypeError("program rule priority must be integer")
    semantic = params.get("semantic")
    if semantic is not None and (
        type(semantic) is not str or not semantic.strip()
    ):
        raise ValueError("program rule semantic must be text or None")
    for field in ("state_matches", "payload_matches", "configuration"):
        if not isinstance(params.get(field), Mapping):
            raise TypeError(f"program rule {field} must be object")


def program_rule_set(
    rules: tuple[NoetriumUnit, ...],
    *,
    max_matches: int | None = 1,
    unhandled: UnhandledEventPolicy = UnhandledEventPolicy.ERROR,
) -> NoetriumUnit:
    if type(rules) is not tuple or not rules:
        raise ValueError("program rule set requires at least one rule Unit")
    for rule in rules:
        validate_program_rule(rule)
    ids = tuple(rule.unit_id for rule in rules)
    if len(ids) != len(set(ids)):
        raise ValueError("program rule ids must be unique")
    if max_matches is not None and (
        type(max_matches) is not int or max_matches < 1
    ):
        raise ValueError("rule dispatch max_matches must be positive or None")
    if not isinstance(unhandled, UnhandledEventPolicy):
        raise TypeError("unhandled policy must be UnhandledEventPolicy")
    return structure_unit(
        "rule-set",
        traits=(PROGRAM_RULE_SET_TRAIT,),
        parameters={
            "max_matches": max_matches,
            "unhandled": unhandled.value,
        },
        members=rules,
    )


def validate_program_rule_set(rules: NoetriumUnit) -> None:
    if type(rules) is not NoetriumUnit or not rules.has_trait(PROGRAM_RULE_SET_TRAIT):
        raise TypeError("program rule set must be machine.rule-set NoetriumUnit")
    if not rules.members:
        raise ValueError("program rule set requires rules")
    for rule in rules.members:
        validate_program_rule(rule)
    ids = tuple(rule.unit_id for rule in rules.members)
    if len(ids) != len(set(ids)):
        raise ValueError("program rule ids must be unique")
    max_matches = rules.parameters.get("max_matches")
    if max_matches is not None and (
        type(max_matches) is not int or max_matches < 1
    ):
        raise ValueError("rule dispatch max_matches must be positive or None")
    UnhandledEventPolicy(str(rules.parameters.get("unhandled")))


def program_rule_payload(rule: NoetriumUnit) -> JsonObject:
    validate_program_rule(rule)
    return {
        "rule_id": rule.unit_id,
        "event_kind": rule.parameters["event_kind"],
        "operation": rule.parameters["operation"],
        "priority": rule.parameters["priority"],
        "semantic": rule.parameters["semantic"],
        "state_matches": rule.parameters["state_matches"],
        "payload_matches": rule.parameters["payload_matches"],
        "configuration": rule.parameters["configuration"],
        "rule_digest": rule.unit_digest,
    }


def program_rule_set_payload(rules: NoetriumUnit) -> JsonObject:
    validate_program_rule_set(rules)
    return {
        "rules": tuple(program_rule_payload(rule) for rule in rules.members),
        "max_matches": rules.parameters["max_matches"],
        "unhandled": rules.parameters["unhandled"],
        "rule_set_digest": rules.unit_digest,
    }


def ordered_program_rules(
    rules: NoetriumUnit,
    event: MachineEvent,
    state: Mapping[str, JsonValue],
) -> tuple[NoetriumUnit, ...]:
    validate_program_rule_set(rules)
    limit = rules.parameters["max_matches"]
    candidates = sorted(
        (
            rule
            for rule in rules.members
            if rule.parameters["event_kind"] == event.kind
        ),
        key=lambda rule: (
            -int(rule.parameters["priority"]),
            rule.unit_id,
        ),
    )
    matches: list[NoetriumUnit] = []
    for rule in candidates:
        state_matchers = tuple(
            (tuple(str(path).split(".")), target)
            for path, target in rule.parameters["state_matches"].items()
        )
        payload_matchers = tuple(
            (tuple(str(path).split(".")), target)
            for path, target in rule.parameters["payload_matches"].items()
        )
        if (
            _matches_compiled(state, state_matchers)
            and _matches_compiled(event.payload, payload_matchers)
        ):
            matches.append(rule)
            if limit is not None and len(matches) >= int(limit):
                break
    return tuple(matches)


def _lookup_parts(
    value: Mapping[str, JsonValue],
    parts: tuple[str, ...],
) -> JsonValue:
    current: object = value
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current  # type: ignore[return-value]


def _matches_compiled(
    value: Mapping[str, JsonValue],
    matchers: tuple[tuple[tuple[str, ...], JsonValue], ...],
) -> bool:
    return all(
        _lookup_parts(value, parts) == target
        for parts, target in matchers
    )


def compile_rule_program(
    *,
    program_id: str,
    domain: str,
    version: str,
    state_schema: str,
    rules: NoetriumUnit,
    required_capabilities: tuple[str, ...] = (),
) -> NoetriumUnit:
    if type(domain) is not str or not domain.strip():
        raise ValueError("rule program domain must be non-empty text")
    domain = domain.strip()
    validate_program_rule_set(rules)
    dispatch = unit_operation(
        "dispatch",
        "program.rule-dispatch",
        configuration={"rule_set": program_rule_set_payload(rules)},
    )
    return executable_unit(
        program_id,
        domain=domain,
        version=version,
        state_schema=state_schema,
        entrypoint="dispatch",
        required_capabilities=required_capabilities,
        members=(dispatch,),
        relations=(unit_flow("dispatch", "dispatch", default=True),),
    )


def _merge_refs(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*left, *right)))


def build_rule_handlers(
    rules: NoetriumUnit,
    downstream: UnitOperationRegistryPort,
) -> UnitOperationRegistry:
    validate_program_rule_set(rules)
    if not isinstance(downstream, UnitOperationRegistryPort):
        raise TypeError("rule downstream must implement UnitOperationRegistryPort")

    registry = UnitOperationRegistry.empty()

    def dispatch(request: UnitStepContext) -> UnitTransition:
        envelope = request.payload
        if not isinstance(envelope, Mapping):
            raise TypeError("rule dispatch requires an event envelope")
        event = MachineEvent.from_payload(envelope.get("event"))
        matches = ordered_program_rules(rules, event, request.data)
        if not matches:
            event_payload = {
                "type": "program_event_unhandled",
                "event_kind": event.kind,
                "policy": str(rules.parameters["unhandled"]),
            }
            unhandled = UnhandledEventPolicy(str(rules.parameters["unhandled"]))
            if unhandled is UnhandledEventPolicy.ERROR:
                raise ValueError(f"unhandled program event: {event.kind}")
            if unhandled is UnhandledEventPolicy.WAIT:
                return UnitTransition.suspend(f'event has no matching rule: {event.kind}', value=event.as_payload(), events=(event_payload,))
            return UnitTransition.goto(value=event.as_payload(), events=(event_payload,))

        data = dict(thaw_json(request.data))
        previous: JsonValue = request.previous_value
        emitted_commands = ()
        events: tuple[JsonValue, ...] = ()
        output_refs: tuple[str, ...] = ()
        effect_refs: tuple[str, ...] = ()
        evidence_refs: tuple[str, ...] = ()
        artifact_refs: tuple[str, ...] = ()
        final_control = None

        for rule in matches:
            handler = downstream.resolve(str(rule.parameters["operation"]))
            configuration = dict(thaw_json(rule.parameters["configuration"]))
            if rule.parameters["semantic"] is not None:
                configuration["semantic"] = rule.parameters["semantic"]
            synthetic = unit_operation(
                f"{request.node.unit_id}.{rule.unit_id}",
                str(rule.parameters["operation"]),
                configuration=configuration,
                required_capabilities=unit_operation_required_capabilities(request.node),
            )
            result = handler(
                UnitStepContext(
                    unit=request.unit,
                    node=synthetic,
                    snapshot=request.snapshot,
                    configuration=freeze_json(configuration),
                    payload=event.payload,
                    data=freeze_json(data),
                    previous_value=previous,
                    visit=request.visit,
                    visit_counts=request.visit_counts,
                    checkpoint_value=request.checkpoint_value,
                    semantic_state=request.semantic_state,
                )
            )
            if not isinstance(result, UnitTransition):
                raise TypeError("program rule handler must return UnitTransition")
            update = thaw_json(result.state.data)
            if not isinstance(update, dict):
                raise TypeError("program rule state delta must decode to an object")
            data.update(update)
            previous = result.value
            emitted_commands = (
                *emitted_commands,
                *result.observation.emitted_commands,
            )
            events = (*events, *result.observation.events)
            output_refs = _merge_refs(
                output_refs,
                result.observation.output_refs,
            )
            effect_refs = _merge_refs(effect_refs, result.intents)
            evidence_refs = _merge_refs(
                evidence_refs,
                result.observation.evidence_refs,
            )
            artifact_refs = _merge_refs(
                artifact_refs,
                result.observation.artifact_refs,
            )
            if isinstance(result.control, (UnitSuspend, UnitHalt)):
                final_control = result.control
                break
            if not isinstance(result.control, UnitGoto):
                raise TypeError("unsupported nested rule control")

        transition_kwargs = {
            "value": previous,
            "state_delta": data,
            "emitted_commands": emitted_commands,
            "events": ({
                "type": "program_event_dispatched",
                "event_kind": event.kind,
                "rule_ids": tuple(rule.unit_id for rule in matches),
                "rule_set_digest": rules.unit_digest,
            }, *events),
            "output_refs": output_refs,
            "intents": effect_refs,
            "evidence_refs": evidence_refs,
            "artifact_refs": artifact_refs,
        }
        if isinstance(final_control, UnitSuspend):
            return UnitTransition.suspend(
                final_control.reason,
                interrupted=(
                    final_control.status is MachineStatus.INTERRUPTED
                ),
                **transition_kwargs,
            )
        if isinstance(final_control, UnitHalt):
            return UnitTransition.halt(
                failed=(final_control.status is MachineStatus.FAILED),
                **transition_kwargs,
            )
        return UnitTransition.goto(**transition_kwargs)

    registry.register(
        "program.rule-dispatch",
        dispatch,
        implementation_digest=canonical_digest({
            "handler_family": "program.rule-dispatch",
            "implementation_revision": 1,
            "rule_set_digest": rules.unit_digest,
            "downstream_handler_identity_digest": downstream.identity_digest,
        }),
    )
    return registry


__all__ = [
    "MachineEvent",
    "PROGRAM_RULE_SET_TRAIT",
    "PROGRAM_RULE_TRAIT",
    "ordered_program_rules",
    "program_rule",
    "program_rule_payload",
    "program_rule_set",
    "program_rule_set_payload",
    "validate_program_rule",
    "validate_program_rule_set",
    "UnhandledEventPolicy",
    "build_rule_handlers",
    "compile_rule_program",
]
