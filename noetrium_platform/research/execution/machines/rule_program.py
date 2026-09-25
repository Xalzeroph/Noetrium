"""Domain-neutral event/rule IR for programmable research Machines.

This module is a reusable semantic layer above ResearchProgram. It lets any
research domain express event-driven transition selection without adding a
domain-specific runner or growing kernel enums.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineKind,
    MachineStatus,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from .program import (
    ProgramHandlerRegistry,
    ProgramHandlerRegistryPort,
    ProgramNode,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchProgram,
    ResearchProgramBuilder,
    core_program_handlers,
)


class RuleDispatchMode(StrEnum):
    FIRST = "first"
    ALL = "all"


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


@dataclass(frozen=True, slots=True)
class ProgramRule:
    rule_id: str
    event_kind: str
    operation: str
    priority: int = 0
    semantic: str | None = None
    state_matches: JsonObject = field(default_factory=dict)
    payload_matches: JsonObject = field(default_factory=dict)
    configuration: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("rule_id", self.rule_id),
            ("event_kind", self.event_kind),
            ("operation", self.operation),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"program rule {name} is required")
            object.__setattr__(self, name, value.strip())
        if type(self.priority) is not int:
            raise TypeError("program rule priority must be an integer")
        if self.semantic is not None and (
            type(self.semantic) is not str or not self.semantic.strip()
        ):
            raise ValueError("program rule semantic must be non-empty when provided")
        for name in ("state_matches", "payload_matches", "configuration"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TypeError(f"program rule {name} must be an object")
            object.__setattr__(self, name, freeze_json(value))

    def as_payload(self) -> JsonObject:
        return {
            "rule_id": self.rule_id,
            "event_kind": self.event_kind,
            "operation": self.operation,
            "priority": self.priority,
            "semantic": self.semantic,
            "state_matches": self.state_matches,
            "payload_matches": self.payload_matches,
            "configuration": self.configuration,
        }


@dataclass(frozen=True, slots=True)
class ProgramRuleSet:
    rules: tuple[ProgramRule, ...]
    mode: RuleDispatchMode = RuleDispatchMode.FIRST
    unhandled: UnhandledEventPolicy = UnhandledEventPolicy.ERROR
    rule_set_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.rules) is not tuple or not self.rules:
            raise ValueError("program rule set requires at least one rule")
        if any(not isinstance(rule, ProgramRule) for rule in self.rules):
            raise TypeError("program rule set must contain ProgramRule values")
        ids = tuple(rule.rule_id for rule in self.rules)
        if len(ids) != len(set(ids)):
            raise ValueError("program rule ids must be unique")
        if not isinstance(self.mode, RuleDispatchMode):
            raise TypeError("rule dispatch mode must be RuleDispatchMode")
        if not isinstance(self.unhandled, UnhandledEventPolicy):
            raise TypeError("unhandled policy must be UnhandledEventPolicy")
        object.__setattr__(
            self,
            "rule_set_digest",
            canonical_digest({
                "rules": tuple(rule.as_payload() for rule in self.rules),
                "mode": self.mode.value,
                "unhandled": self.unhandled.value,
            }),
        )

    def ordered_matches(
        self,
        event: MachineEvent,
        state: Mapping[str, JsonValue],
    ) -> tuple[ProgramRule, ...]:
        matches = tuple(
            rule
            for rule in self.rules
            if rule.event_kind == event.kind
            and _matches(state, rule.state_matches)
            and _matches(event.payload, rule.payload_matches)
        )
        ordered = tuple(
            sorted(matches, key=lambda rule: (-rule.priority, rule.rule_id))
        )
        return ordered[:1] if self.mode is RuleDispatchMode.FIRST else ordered

    def as_payload(self) -> JsonObject:
        return {
            "rules": tuple(rule.as_payload() for rule in self.rules),
            "mode": self.mode.value,
            "unhandled": self.unhandled.value,
            "rule_set_digest": self.rule_set_digest,
        }


def _lookup(value: Mapping[str, JsonValue], path: str) -> JsonValue:
    current: object = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current  # type: ignore[return-value]


def _matches(
    value: Mapping[str, JsonValue],
    expected: Mapping[str, JsonValue],
) -> bool:
    return all(_lookup(value, path) == target for path, target in expected.items())


def compile_rule_program(
    *,
    program_id: str,
    kind: MachineKind,
    version: str,
    state_schema: str,
    rules: ProgramRuleSet,
    required_capabilities: tuple[str, ...] = (),
) -> ResearchProgram:
    if not isinstance(kind, MachineKind) or kind is MachineKind.METHOD:
        raise ValueError("rule program requires a non-Method MachineKind")
    if not isinstance(rules, ProgramRuleSet):
        raise TypeError("compile_rule_program requires ProgramRuleSet")
    return (
        ResearchProgramBuilder(
            program_id=program_id,
            kind=kind,
            version=version,
            state_schema=state_schema,
            entrypoint="dispatch",
            required_capabilities=required_capabilities,
        )
        .node(
            "dispatch",
            "program.rule-dispatch",
            configuration={"rule_set": rules.as_payload()},
            next_node="dispatch",
        )
        .build()
    )


def _merge_refs(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*left, *right)))


def build_rule_handlers(
    rules: ProgramRuleSet,
    downstream: ProgramHandlerRegistryPort,
) -> ProgramHandlerRegistry:
    if not isinstance(rules, ProgramRuleSet):
        raise TypeError("rule handlers require ProgramRuleSet")
    if not isinstance(downstream, ProgramHandlerRegistryPort):
        raise TypeError("rule downstream must implement ProgramHandlerRegistryPort")

    registry = core_program_handlers()

    def dispatch(request: ProgramNodeRequest) -> ProgramNodeResult:
        envelope = request.payload
        if not isinstance(envelope, Mapping):
            raise TypeError("rule dispatch requires an event envelope")
        event = MachineEvent.from_payload(envelope.get("event"))
        matches = rules.ordered_matches(event, request.data)
        if not matches:
            event_payload = {
                "type": "program_event_unhandled",
                "event_kind": event.kind,
                "policy": rules.unhandled.value,
            }
            if rules.unhandled is UnhandledEventPolicy.ERROR:
                raise ValueError(f"unhandled program event: {event.kind}")
            if rules.unhandled is UnhandledEventPolicy.WAIT:
                return ProgramNodeResult(
                    value=event.as_payload(),
                    status=MachineStatus.WAITING,
                    wait_reason=f"event has no matching rule: {event.kind}",
                    events=(event_payload,),
                )
            return ProgramNodeResult(
                value=event.as_payload(),
                events=(event_payload,),
            )

        data = dict(thaw_json(request.data))
        previous: JsonValue = request.previous_value
        emitted_commands = ()
        events: tuple[JsonValue, ...] = ()
        output_refs: tuple[str, ...] = ()
        effect_refs: tuple[str, ...] = ()
        evidence_refs: tuple[str, ...] = ()
        artifact_refs: tuple[str, ...] = ()
        final_status: MachineStatus | None = None
        wait_reason: str | None = None

        for rule in matches:
            handler = downstream.resolve(rule.operation)
            configuration = dict(thaw_json(rule.configuration))
            if rule.semantic is not None:
                configuration["semantic"] = rule.semantic
            synthetic = ProgramNode(
                node_id=f"{request.node.node_id}:{rule.rule_id}",
                operation=rule.operation,
                configuration=configuration,
                required_capabilities=request.node.required_capabilities,
            )
            result = handler(
                ProgramNodeRequest(
                    program=request.program,
                    node=synthetic,
                    snapshot=request.snapshot,
                    payload=event.payload,
                    data=data,
                    previous_value=previous,
                    visit=request.visit,
                )
            )
            if not isinstance(result, ProgramNodeResult):
                raise TypeError("program rule handler must return ProgramNodeResult")
            update = thaw_json(result.state_update)
            if not isinstance(update, dict):
                raise TypeError("program rule state update must decode to an object")
            data.update(update)
            previous = result.value
            emitted_commands = (*emitted_commands, *result.emitted_commands)
            events = (*events, *result.events)
            output_refs = _merge_refs(output_refs, result.output_refs)
            effect_refs = _merge_refs(effect_refs, result.effect_intent_refs)
            evidence_refs = _merge_refs(evidence_refs, result.evidence_refs)
            artifact_refs = _merge_refs(artifact_refs, result.artifact_refs)
            if result.status is not None:
                final_status = result.status
                wait_reason = result.wait_reason
            if final_status in {
                MachineStatus.WAITING,
                MachineStatus.INTERRUPTED,
                MachineStatus.COMPLETED,
                MachineStatus.FAILED,
            }:
                break

        return ProgramNodeResult(
            value=previous,
            state_update=data,
            status=final_status,
            wait_reason=wait_reason,
            emitted_commands=emitted_commands,
            events=({
                "type": "program_event_dispatched",
                "event_kind": event.kind,
                "rule_ids": tuple(rule.rule_id for rule in matches),
                "rule_set_digest": rules.rule_set_digest,
            }, *events),
            output_refs=output_refs,
            effect_intent_refs=effect_refs,
            evidence_refs=evidence_refs,
            artifact_refs=artifact_refs,
        )

    registry.register(
        "program.rule-dispatch",
        dispatch,
        implementation_digest=canonical_digest({
            "handler_family": "program.rule-dispatch",
            "implementation_revision": 1,
            "rule_set_digest": rules.rule_set_digest,
            "downstream_handler_identity_digest": downstream.identity_digest,
        }),
    )
    return registry


__all__ = [
    "MachineEvent",
    "ProgramRule",
    "ProgramRuleSet",
    "RuleDispatchMode",
    "UnhandledEventPolicy",
    "build_rule_handlers",
    "compile_rule_program",
]
