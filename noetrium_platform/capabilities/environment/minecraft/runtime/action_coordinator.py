from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonValue,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import unit_document
from noetrium_platform.foundation.kernel.record import record_payload
from noetrium_platform.substrate.api import prepared_handle_field

from ..api import (
    MINECRAFT_ACTION_TYPES,
    MINECRAFT_ACTION_SPEC_BY_TYPE,
    minecraft_action_effect_class,
    minecraft_action_side_effect_envelope,
    minecraft_action_planner_contract,
    minecraft_action_unavailable_dependencies,
    minecraft_action_authorization_unit,
    minecraft_action_invocation_unit,
    MinecraftActionContractError,
    MinecraftActionOutcomeStatus,
    minecraft_action_result_record,
    MinecraftObservationEvent,
    minecraft_action_timeout,
    minecraft_transition_unit,
    validate_minecraft_action,
)
from ..api.ports import MinecraftBridgePort
from ..api.usage_guides import minecraft_action_usage_guide
from .action_ledger import MinecraftActionLedger
from .action_recovery import MinecraftActionRecoveryCodec
from .checkpoint import MinecraftActionResolution
from .errors import MinecraftEnvironmentFailure
from .event_views import minecraft_events_payload
from .session_diagnostics import safe_exception_message


def _minecraft_action_effect_class(action_type: str) -> EffectClass:
    """Read replay/recovery semantics from the authoritative action Unit."""
    spec = MINECRAFT_ACTION_SPEC_BY_TYPE.get(action_type)
    if spec is None:
        return EffectClass.RECONCILABLE
    return minecraft_action_effect_class(spec)


class EventLogger(Protocol):
    def __call__(
        self,
        phase: str,
        event: str,
        *,
        level: str = "DEBUG",
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
    ) -> None: ...


class FailureLogger(Protocol):
    def __call__(
        self, phase: str, exc: BaseException, *, code: str | None = None
    ) -> None: ...


class EventIngester(Protocol):
    def __call__(
        self,
        events: tuple[MinecraftObservationEvent, ...],
        *,
        phase: str,
    ) -> None: ...


class ObservationFactory(Protocol):
    def __call__(
        self,
        *,
        payload: Mapping[str, JsonValue],
        artifact_refs: tuple[str, ...] = (),
    ) -> Observation: ...


class StatePayloadFactory(Protocol):
    def __call__(self) -> Mapping[str, JsonValue]: ...


class LastObservationFactory(Protocol):
    def __call__(self) -> Observation | None: ...


class DecisionViewFactory(Protocol):
    def __call__(
        self,
        *,
        detailed_entities: bool = False,
        include_entities: bool = True,
        snapshot_state: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...


@dataclass(frozen=True, slots=True)
class MinecraftActionCoordinatorBindings:
    event_log: EventLogger
    failure_log: FailureLogger
    ingest_events: EventIngester
    observation: ObservationFactory
    state_payload: StatePayloadFactory
    last_observation: LastObservationFactory
    decision_view: DecisionViewFactory | None = None


class MinecraftActionCoordinator:
    """Own Minecraft action identity, execution, recovery and reconciliation."""

    def __init__(
        self,
        *,
        session_id: str,
        generation: str,
        provider_instance_id: str,
        command_timeout_s: float,
        bridge: MinecraftBridgePort,
        bindings: MinecraftActionCoordinatorBindings,
        allowed_action_types: frozenset[str] = MINECRAFT_ACTION_TYPES,
        actions: Mapping[str, MinecraftActionResolution] | None = None,
    ) -> None:
        self._session_id = session_id
        self._generation = generation
        self._provider_instance_id = provider_instance_id
        if (
            isinstance(command_timeout_s, bool)
            or not isinstance(command_timeout_s, (int, float))
            or float(command_timeout_s) <= 0
        ):
            raise ValueError("Minecraft action command_timeout_s must be positive")
        self._command_timeout_s = float(command_timeout_s)
        if not isinstance(allowed_action_types, frozenset) or not allowed_action_types.issubset(MINECRAFT_ACTION_TYPES):
            raise ValueError("Minecraft action permission subset is invalid")
        self._allowed_action_types = allowed_action_types
        self._bridge = bridge
        self._bindings = bindings
        self._ledger = MinecraftActionLedger(actions)

    def _terminal_settlement_seconds(self) -> float:
        raw = getattr(self._bridge, "terminal_settlement_timeout_s", 0.0)
        if (
            isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and math.isfinite(float(raw))
            and float(raw) > 0.0
        ):
            return float(raw)
        return 0.0

    @property
    def minimum_action_execution_seconds(self) -> float:
        # The bridge wire represents semantic time in integer milliseconds; a
        # newly effectful action therefore needs one semantic millisecond plus
        # the provider-declared terminal settlement reserve.
        return self._terminal_settlement_seconds() + 0.001

    def _journal_world_transition(self, transition: NoetriumUnit, action_id: str) -> None:
        # A journal-only Unit never becomes agent-visible world knowledge.
        # An unacknowledged operation has explicitly unknown effect certainty.
        self._bindings.event_log(
            "act",
            "MC_WORLD_TRANSITION",
            level="INFO",
            attributes={
                "unit": thaw_json(unit_document(transition)),
                "unit_digest": transition.unit_digest,
            },
            correlation_refs=(action_id, transition.unit_digest),
        )

    def snapshot(self) -> dict[str, MinecraftActionResolution]:
        return self._ledger.snapshot()

    def replace(self, values: Mapping[str, MinecraftActionResolution]) -> None:
        self._ledger = MinecraftActionLedger(values)

    def __len__(self) -> int:
        return len(self._ledger)

    def _contract_rejection_result(
        self,
        request: ActionRequest,
        *,
        code: str,
        message: str,
        invocation: NoetriumUnit | None = None,
        contract_validation: str = "not_reached",
    ) -> ActionResult:
        request_digest = action_request_digest(request)
        invocation = (
            minecraft_action_invocation_unit(request)
            if invocation is None
            else invocation
        )
        authorization = minecraft_action_authorization_unit(
            invocation,
            allowed_action_types=self._allowed_action_types,
            contract_validation=contract_validation,
            rejection_code=code,
        )
        prior = self._ledger.get(request.action_id)
        if prior is None:
            self._ledger.record(
                action_id=request.action_id,
                request_digest=request_digest,
                disposition=ActionReconciliationDisposition.REJECTED,
                invocation_unit_digest=invocation.unit_digest,
                authorization_unit_digest=authorization.unit_digest,
            )
        elif (
            prior.request_digest != request_digest
            or prior.disposition is not ActionReconciliationDisposition.REJECTED
        ):
            raise ActionIdentityViolation(
                "Minecraft contract rejection contradicts the action ledger"
            )
        receipt = EffectReceipt(
            effect_id=f"minecraft-action:{request.action_id}",
            request_digest=request_digest,
            effect_class=_minecraft_action_effect_class(request.action_type),
            certainty=EffectCertainty.EFFECT_REJECTED,
            provider_instance_id=self._provider_instance_id,
            provider_receipt=request.action_id,
        )
        previous = self._bindings.last_observation()
        observation_payload: dict[str, JsonValue] = {
            "kind": "minecraft_action_result",
            "action_id": request.action_id,
            "action_type": request.action_type,
            "effect_disposition": ActionReconciliationDisposition.REJECTED.value,
            "outcome_status": MinecraftActionOutcomeStatus.REJECTED.value,
            "contract_rejection": {"code": code, "message": message},
            **self._bindings.state_payload(),
        }
        if self._bindings.decision_view is not None:
            state = observation_payload.get("state")
            if isinstance(state, Mapping):
                observation_payload["decision_view"] = dict(
                    self._bindings.decision_view(
                        detailed_entities=False,
                        include_entities=False,
                        snapshot_state=state,
                    )
                )
        observation = self._bindings.observation(payload=observation_payload)
        state_digest = observation_payload.get("state_digest")
        if not isinstance(state_digest, str):
            state_digest = None
        transition = minecraft_transition_unit(
            invocation=invocation,
            authorization=authorization,
            provider_instance_id=self._provider_instance_id,
            before_observation_id=(
                previous.observation_id if previous is not None else None
            ),
            after_observation_id=(
                observation.observation_id
                if isinstance(observation, Observation)
                else None
            ),
            state_digest=state_digest,
            outcome_status=MinecraftActionOutcomeStatus.REJECTED.value,
            effect_disposition=ActionReconciliationDisposition.REJECTED.value,
            action_result_digest=None,
            effect_receipt_id=receipt.effect_id,
            bridge_acknowledged=False,
            failure_code=code,
            provider_outcome={
                "status": MinecraftActionOutcomeStatus.REJECTED.value,
                "code": code,
                "message": message,
                "source": "capability_authorization",
            },
        )
        self._journal_world_transition(transition, request.action_id)
        self._bindings.event_log(
            "act.contract",
            "MC_ACTION_CONTRACT_REJECTED",
            level="WARNING",
            attributes={
                "action_id": request.action_id,
                "action_type": request.action_type,
                "code": code,
                "invocation_unit_digest": invocation.unit_digest,
                "authorization_unit_digest": authorization.unit_digest,
            },
            correlation_refs=(
                request.action_id,
                invocation.unit_digest,
                authorization.unit_digest,
            ),
        )
        return ActionResult(
            action_id=request.action_id,
            accepted=False,
            observation=observation if isinstance(observation, Observation) else None,
            effect=receipt,
            diagnostics={
                "environment": "minecraft",
                "action_type": request.action_type,
                "effect_disposition": ActionReconciliationDisposition.REJECTED.value,
                "outcome_status": MinecraftActionOutcomeStatus.REJECTED.value,
                "contract_rejection_code": code,
                "contract_rejection_message": message,
                "action_invocation_unit_digest": invocation.unit_digest,
                "action_authorization_unit_digest": authorization.unit_digest,
                "world_transition_digest": transition.unit_digest,
            },
        )

    def act(self, request: ActionRequest, control: ExecutionControlPort) -> ActionResult:
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("Minecraft action requires ExecutionControlPort")
        control.checkpoint()
        request_digest = self._ledger.assert_new(request)
        invocation = minecraft_action_invocation_unit(request)
        self._bindings.event_log(
            "act",
            "MC_ACTION_START",
            attributes={
                "action_id": request.action_id,
                "action_type": request.action_type,
                "invocation_unit_digest": invocation.unit_digest,
            },
            correlation_refs=(request.action_id, invocation.unit_digest),
        )
        if request.action_type not in self._allowed_action_types:
            return self._contract_rejection_result(
                request, code="ACTION_NOT_AUTHORIZED",
                message="The current paper environment forbids this action",
                invocation=invocation,
            )
        missing = minecraft_action_unavailable_dependencies(
            request.action_type, self._allowed_action_types
        )
        if missing:
            return self._contract_rejection_result(
                request,
                code="ACTION_CHILD_CAPABILITY_NOT_AUTHORIZED",
                message="Composite action lacks authorized child capabilities: " + ", ".join(missing),
                invocation=invocation,
            )
        try:
            payload = validate_minecraft_action(request.action_type, request.payload)
        except MinecraftActionContractError as exc:
            self._bindings.failure_log("act.contract", exc, code=exc.code)
            raise MinecraftEnvironmentFailure(
                "act.contract", safe_exception_message(exc), cause_code=exc.code
            ) from exc
        normalized_action = dict(payload)
        if request.action_type == "describe_action":
            # Derive help exclusively from the CURRENT authorized Unit catalog,
            # never from client-supplied metadata or a second JS-side schema.
            # Unauthorized target names cannot be used to enumerate capabilities.
            target = normalized_action["action_type"]
            if target not in self._allowed_action_types:
                return self._contract_rejection_result(
                    request,
                    code="ACTION_HELP_TARGET_NOT_AUTHORIZED",
                    message="No public action documentation for an unavailable action",
                    invocation=invocation,
                    contract_validation="passed",
                )
            reference = minecraft_action_planner_contract(
                MINECRAFT_ACTION_SPEC_BY_TYPE[target]
            ).as_payload()
            # Guide is attached only AFTER Authority verifies the requested
            # target. Default catalog and other model turns do not carry
            # long examples or prohibited-call demonstrations.
            # Frozen schemas carry MappingProxyTypes. Thaw to plain JSON only
            # at this pre-bridge boundary, without touching physical truth.
            authorized_help = thaw_json(reference)
            authorized_help["usage_guide"] = minecraft_action_usage_guide(target)
            payload["_authorized_action_reference"] = authorized_help

        authorization = minecraft_action_authorization_unit(
            invocation,
            allowed_action_types=self._allowed_action_types,
            contract_validation="passed",
        )
        authorized_children = tuple(
            str(name) for name in authorization.attributes["authorized_child_actions"]
        )
        payload["_authorized_child_action_units"] = {
            name: MINECRAFT_ACTION_SPEC_BY_TYPE[name].unit_digest
            for name in authorized_children
        }
        payload["_authorized_child_max_depth"] = int(
            authorization.attributes["max_child_depth"]
        )
        payload["_action_invocation_unit_digest"] = invocation.unit_digest
        payload["_action_authorization_unit_digest"] = authorization.unit_digest
        payload["_action_effect_class"] = _minecraft_action_effect_class(
            request.action_type
        ).value
        payload["_action_side_effect_envelope"] = [
            domain.value
            for domain in minecraft_action_side_effect_envelope(
                MINECRAFT_ACTION_SPEC_BY_TYPE[request.action_type]
            )
        ]
        payload.update(
            {
                "action_id": request.action_id,
                "_request_digest": request_digest,
                "context": {
                    "run_id": request.context.run_id,
                    "study_id": request.context.study_id,
                    "task_id": request.context.task_id,
                    "decision_cycle_id": request.context.decision_cycle_id,
                },
            }
        )
        # The workload Scope is the outer scientific deadline; the action
        # catalog is the inner liveness authority.  A bounded semantic action
        # must never inherit an arbitrarily larger remaining workload budget:
        # otherwise one pathological provider/pathfinder call can consume the
        # entire Trial before the Method can observe failure and recover.
        catalog_timeout_s = minecraft_action_timeout(
            request.action_type, self._command_timeout_s
        )
        remaining_seconds = control.remaining_seconds
        if remaining_seconds is None:
            action_timeout_s = catalog_timeout_s
        else:
            if remaining_seconds <= 0.0:
                control.checkpoint()
            action_timeout_s = min(remaining_seconds, catalog_timeout_s)
        # Preserve one outer transport deadline while budgeting provider
        # terminal settlement inside it. Milliseconds are the bridge wire
        # representation; floor ensures the semantic action can never consume
        # settlement time through conversion rounding.
        settlement_s = self._terminal_settlement_seconds()
        # The transport watchdog remains the exact catalog/Scope deadline.
        # Reserve provider-declared time *inside* that same budget so semantic
        # cancellation can quiesce, project terminal evidence, and publish the
        # action_result/ACK before the host transport deadline. If the outer
        # Scope cannot fit that provider contract, fail before physical submit:
        # knowingly sending would manufacture avoidable UNKNOWN effects.
        semantic_timeout_s = action_timeout_s - settlement_s
        semantic_timeout_ms = math.floor(semantic_timeout_s * 1000)
        if semantic_timeout_ms < 1:
            code = "MINECRAFT_ACTION_SETTLEMENT_BUDGET_EXHAUSTED"
            exc = RuntimeError(
                "remaining action budget cannot contain provider terminal settlement; "
                f"action_budget_s={action_timeout_s:.6f}; "
                f"terminal_settlement_s={settlement_s:.6f}"
            )
            self._bindings.failure_log("act.deadline", exc, code=code)
            raise MinecraftEnvironmentFailure(
                "act.deadline", safe_exception_message(exc), cause_code=code
            ) from exc
        payload["_action_timeout_ms"] = semantic_timeout_ms
        # Composite actions may legitimately span multiple provider primitives
        # (navigation, one physical effect, pickup verification, ...).  The
        # catalog multiplier expands the *whole action* liveness budget; it
        # must not silently let any single primitive inherit that multiplied
        # deadline.  Publish the semantic window of one ordinary provider
        # action so the bridge can bound each physical segment without
        # re-deriving catalog policy or introducing benchmark-specific timers.
        base_semantic_timeout_s = self._command_timeout_s - settlement_s
        provider_window_s = min(semantic_timeout_s, base_semantic_timeout_s)
        provider_window_ms = math.floor(provider_window_s * 1000)
        if provider_window_ms < 1:
            code = "MINECRAFT_ACTION_PROVIDER_WINDOW_EXHAUSTED"
            exc = RuntimeError(
                "provider primitive budget cannot contain terminal settlement; "
                f"base_action_budget_s={self._command_timeout_s:.6f}; "
                f"terminal_settlement_s={settlement_s:.6f}"
            )
            self._bindings.failure_log("act.deadline", exc, code=code)
            raise MinecraftEnvironmentFailure(
                "act.deadline", safe_exception_message(exc), cause_code=code
            ) from exc
        payload["_action_provider_window_ms"] = provider_window_ms
        try:
            result = self._bridge.command(
                request.action_type,
                payload,
                timeout_s=action_timeout_s,
                control=control,
            )
            control.checkpoint()
        except Exception as exc:
            # Absence of a terminal ACK is *not* evidence of no physical effect.
            # Fence this exact request identity as UNKNOWN before returning the
            # failure: the same action_id may only proceed through reconcile,
            # never through a blind physical retry.
            self._ledger.resolve(
                action_id=request.action_id,
                request_digest=request_digest,
                disposition=ActionReconciliationDisposition.UNKNOWN,
                invocation_unit_digest=invocation.unit_digest,
                authorization_unit_digest=authorization.unit_digest,
            )
            previous = self._bindings.last_observation()
            unresolved = minecraft_transition_unit(
                invocation=invocation,
                authorization=authorization,
                provider_instance_id=self._provider_instance_id,
                before_observation_id=previous.observation_id if previous else None,
                after_observation_id=None,
                state_digest=None,
                outcome_status="unresolved",
                effect_disposition=ActionReconciliationDisposition.UNKNOWN.value,
                action_result_digest=None,
                effect_receipt_id=None,
                bridge_acknowledged=False,
                failure_code=str(getattr(exc, "cause_code", "MINECRAFT_ACTION_FAILED")),
            )
            self._journal_world_transition(unresolved, request.action_id)
            self._bindings.failure_log("act", exc)
            raise MinecraftEnvironmentFailure(
                "act",
                safe_exception_message(exc),
                cause_code=str(getattr(exc, "cause_code", "MINECRAFT_ACTION_FAILED")),
            ) from exc

        evidence: minecraft_action_result_record | None = None
        event_payload: Mapping[str, JsonValue] = {}
        for event in result.events:
            if event.kind != "action_result":
                continue
            event_payload = event.payload
            try:
                evidence = minecraft_action_result_record(
                    event,
                    expected_action_id=request.action_id,
                    expected_action_type=request.action_type,
                    expected_request_digest=request_digest,
                    expected_invocation_unit_digest=invocation.unit_digest,
                    expected_authorization_unit_digest=authorization.unit_digest,
                )
            except ValueError as exc:
                self._ledger.resolve(
                    action_id=request.action_id,
                    request_digest=request_digest,
                    disposition=ActionReconciliationDisposition.UNKNOWN,
                    invocation_unit_digest=invocation.unit_digest,
                    authorization_unit_digest=authorization.unit_digest,
                )
                self._bindings.failure_log(
                    "act.evidence", exc, code="MINECRAFT_ACTION_EVIDENCE_INVALID"
                )
                raise MinecraftEnvironmentFailure(
                    "act.evidence",
                    safe_exception_message(exc),
                    cause_code="MINECRAFT_ACTION_EVIDENCE_INVALID",
                ) from exc
            break
        if evidence is None:
            self._ledger.resolve(
                action_id=request.action_id,
                request_digest=request_digest,
                disposition=ActionReconciliationDisposition.UNKNOWN,
                invocation_unit_digest=invocation.unit_digest,
                authorization_unit_digest=authorization.unit_digest,
            )
            bridge_error = result.diagnostics.get("error")
            if isinstance(bridge_error, str) and bridge_error.strip():
                code = "MINECRAFT_ACTION_BRIDGE_REJECTED_WITHOUT_EVIDENCE"
                exc = ValueError(
                    "bridge rejected action without identity-bound action_result "
                    "evidence: " + bridge_error.strip()
                )
            else:
                code = "MINECRAFT_ACTION_EVIDENCE_MISSING"
                exc = ValueError(
                    "bridge returned no identity-bound action_result evidence"
                )
            self._bindings.failure_log("act.evidence", exc, code=code)
            raise MinecraftEnvironmentFailure(
                "act.evidence",
                safe_exception_message(exc),
                cause_code=code,
            ) from exc
        self._bindings.ingest_events(result.events, phase="act")
        evidence_payload = record_payload(evidence)
        raw_child_effects = evidence_payload.get("child_effects", ())
        if type(raw_child_effects) is not tuple or any(
            not isinstance(row, Mapping) for row in raw_child_effects
        ):
            raise MinecraftEnvironmentFailure(
                "act.evidence",
                "validated child effect evidence lost its typed tuple representation",
                cause_code="MINECRAFT_CHILD_EFFECT_EVIDENCE_INVALID",
            )
        accepted = bool(result.acknowledged) and (
            evidence_payload["status"] != MinecraftActionOutcomeStatus.REJECTED.value
        )
        if result.diagnostics.get("error"):
            accepted = False
        certainty = {
            ActionReconciliationDisposition.APPLIED: EffectCertainty.EFFECT_CONFIRMED,
            ActionReconciliationDisposition.REJECTED: EffectCertainty.EFFECT_REJECTED,
            ActionReconciliationDisposition.NOT_APPLIED: EffectCertainty.NO_EFFECT,
            ActionReconciliationDisposition.UNKNOWN: EffectCertainty.INDETERMINATE,
        }[ActionReconciliationDisposition(str(evidence_payload["effect_disposition"]))]
        previous = self._bindings.last_observation()
        receipt = EffectReceipt(
            effect_id=f"minecraft-action:{request.action_id}",
            request_digest=request_digest,
            effect_class=_minecraft_action_effect_class(request.action_type),
            certainty=certainty,
            provider_instance_id=self._provider_instance_id,
            before_artifact=previous.observation_id if previous else None,
            after_artifact=canonical_digest(event_payload) if event_payload else None,
            provider_receipt=request.action_id,
        )
        self._ledger.resolve(
            action_id=request.action_id,
            request_digest=request_digest,
            disposition=ActionReconciliationDisposition(str(evidence_payload["effect_disposition"])),
            invocation_unit_digest=invocation.unit_digest,
            authorization_unit_digest=authorization.unit_digest,
        )
        self._bindings.event_log(
            "act",
            "MC_ACTION_END",
            level="INFO" if accepted else "WARNING",
            attributes={
                "action_id": request.action_id,
                "action_type": request.action_type,
                "outcome_status": str(evidence_payload["status"]),
                "accepted": accepted,
                "effect_disposition": str(evidence_payload["effect_disposition"]),
            },
            correlation_refs=(request.action_id,),
        )
        observation_payload: dict[str, JsonValue] = {
            "kind": "minecraft_action_result",
            "action_id": request.action_id,
            "action_type": request.action_type,
            "effect_disposition": str(evidence_payload["effect_disposition"]),
            "outcome_status": str(evidence_payload["status"]),
            "events": minecraft_events_payload(result.events),
            "bridge_diagnostics": dict(result.diagnostics),
            **self._bindings.state_payload(),
        }
        if self._bindings.decision_view is not None:
            observation_payload["decision_view"] = dict(
                self._bindings.decision_view(
                    detailed_entities=request.action_type == "observe_entities",
                    include_entities=any(
                        event.kind == "entity_snapshot" for event in result.events
                    ),
                    snapshot_state=observation_payload["state"],
                )
            )
        observation = self._bindings.observation(payload=observation_payload)
        transition = minecraft_transition_unit(
            invocation=invocation,
            authorization=authorization,
            provider_instance_id=self._provider_instance_id,
            before_observation_id=previous.observation_id if previous else None,
            after_observation_id=observation.observation_id,
            state_digest=str(observation_payload["state_digest"]),
            outcome_status=str(evidence_payload["status"]),
            provider_outcome=evidence_payload["outcome"],
            execution_control=(
                event_payload.get("execution_control")
                if isinstance(event_payload.get("execution_control"), Mapping)
                else None
            ),
            effect_disposition=str(evidence_payload["effect_disposition"]),
            action_result_digest=canonical_digest(event_payload),
            effect_receipt_id=receipt.effect_id,
            bridge_acknowledged=bool(result.acknowledged),
            child_effects=raw_child_effects,
        )
        self._journal_world_transition(transition, request.action_id)
        return ActionResult(
            action_id=request.action_id,
            accepted=accepted,
            observation=observation,
            effect=receipt,
            diagnostics={
                "environment": "minecraft",
                "action_type": request.action_type,
                "effect_disposition": str(evidence_payload["effect_disposition"]),
                "outcome_status": str(evidence_payload["status"]),
                "bridge_acknowledged": result.acknowledged,
                "provider_outcome": dict(evidence_payload["outcome"]),
                "physical_child_effect_count": len(raw_child_effects),
                "action_invocation_unit_digest": invocation.unit_digest,
                "action_authorization_unit_digest": authorization.unit_digest,
                "world_transition_digest": transition.unit_digest,
            },
        )

    def _prepared_unit_identity(
        self,
        request: ActionRequest,
        *,
        contract_validation: str,
        rejection_code: str | None,
    ) -> tuple[NoetriumUnit, NoetriumUnit]:
        invocation = minecraft_action_invocation_unit(request)
        authorization = minecraft_action_authorization_unit(
            invocation,
            allowed_action_types=self._allowed_action_types,
            contract_validation=contract_validation,
            rejection_code=rejection_code,
        )
        return invocation, authorization

    def _require_prepared_unit_identity(
        self,
        request: ActionRequest,
        prepared,
    ) -> tuple[NoetriumUnit, NoetriumUnit]:
        invocation, authorization = self._prepared_unit_identity(
            request,
            contract_validation=prepared.contract_validation,
            rejection_code=prepared.rejection_code,
        )
        if invocation.unit_digest != prepared.invocation_unit_digest:
            raise ActionIdentityViolation(
                "Minecraft prepared invocation Unit identity drift"
            )
        if authorization.unit_digest != prepared.authorization_unit_digest:
            raise ActionIdentityViolation(
                "Minecraft prepared authorization Unit identity drift"
            )
        return invocation, authorization

    def prepare_action_recovery(
        self,
        request: ActionRequest,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> NoetriumUnit:
        control.checkpoint()
        if request.context != context:
            raise ActionIdentityViolation("Minecraft prepared action context mismatch")
        invocation = minecraft_action_invocation_unit(request)
        if request.action_type not in self._allowed_action_types:
            authorization = minecraft_action_authorization_unit(
                invocation,
                allowed_action_types=self._allowed_action_types,
                contract_validation="not_reached",
                rejection_code="ACTION_NOT_AUTHORIZED",
            )
            return MinecraftActionRecoveryCodec.prepare(
                request,
                session_id=self._session_id,
                generation=self._generation,
                provider_instance_id=self._provider_instance_id,
                invocation_unit_digest=invocation.unit_digest,
                authorization_unit_digest=authorization.unit_digest,
                contract_validation="not_reached",
                rejection_code="ACTION_NOT_AUTHORIZED",
                rejection_message="The current paper environment forbids this action",
            )
        missing = minecraft_action_unavailable_dependencies(
            request.action_type, self._allowed_action_types
        )
        if missing:
            authorization = minecraft_action_authorization_unit(
                invocation,
                allowed_action_types=self._allowed_action_types,
                contract_validation="not_reached",
                rejection_code="ACTION_CHILD_CAPABILITY_NOT_AUTHORIZED",
            )
            return MinecraftActionRecoveryCodec.prepare(
                request,
                session_id=self._session_id,
                generation=self._generation,
                provider_instance_id=self._provider_instance_id,
                invocation_unit_digest=invocation.unit_digest,
                authorization_unit_digest=authorization.unit_digest,
                contract_validation="not_reached",
                rejection_code="ACTION_CHILD_CAPABILITY_NOT_AUTHORIZED",
                rejection_message="Composite action lacks authorized child capabilities: " + ", ".join(missing),
            )
        try:
            validate_minecraft_action(request.action_type, request.payload)
        except MinecraftActionContractError as exc:
            authorization = minecraft_action_authorization_unit(
                invocation,
                allowed_action_types=self._allowed_action_types,
                contract_validation="failed",
                rejection_code=exc.code,
            )
            return MinecraftActionRecoveryCodec.prepare(
                request,
                session_id=self._session_id,
                generation=self._generation,
                provider_instance_id=self._provider_instance_id,
                invocation_unit_digest=invocation.unit_digest,
                authorization_unit_digest=authorization.unit_digest,
                contract_validation="failed",
                rejection_code=exc.code,
                rejection_message=safe_exception_message(exc),
            )
        authorization = minecraft_action_authorization_unit(
            invocation,
            allowed_action_types=self._allowed_action_types,
            contract_validation="passed",
        )
        handle = MinecraftActionRecoveryCodec.prepare(
            request,
            session_id=self._session_id,
            generation=self._generation,
            provider_instance_id=self._provider_instance_id,
            invocation_unit_digest=invocation.unit_digest,
            authorization_unit_digest=authorization.unit_digest,
            contract_validation="passed",
        )
        # Provider PREPARED must be crash-durable before the outer capability
        # layer is allowed to publish its own PREPARED intent.  Reconciliation
        # can then prove NOT_APPLIED before execution starts, while BEGIN moves
        # the provider WAL to UNKNOWN before any physical handler is invoked.
        self._bridge.prepare_action(
            request.action_id,
            request_digest=str(prepared_handle_field(handle, "request_digest")),
            action_type=request.action_type,
            invocation_unit_digest=invocation.unit_digest,
            authorization_unit_digest=authorization.unit_digest,
        )
        return handle

    def execute_prepared_action(
        self,
        request: ActionRequest,
        handle: NoetriumUnit,
        control: ExecutionControlPort,
    ) -> ActionResult:
        prepared = MinecraftActionRecoveryCodec.require_request(
            request,
            handle,
            session_id=self._session_id,
            generation=self._generation,
            provider_instance_id=self._provider_instance_id,
        )
        invocation, _authorization = self._require_prepared_unit_identity(
            request, prepared
        )
        if prepared.rejection_code is not None:
            assert prepared.rejection_message is not None
            return self._contract_rejection_result(
                request,
                code=prepared.rejection_code,
                message=prepared.rejection_message,
                invocation=invocation,
                contract_validation=prepared.contract_validation,
            )
        return self.act(request, control)

    def reconcile_prepared_action(
        self,
        handle: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> ActionReconciliationResult:
        control.checkpoint()
        prepared = MinecraftActionRecoveryCodec.decode(
            handle,
            session_id=self._session_id,
            generation=self._generation,
            provider_instance_id=self._provider_instance_id,
        )
        request = ActionRequest(str(prepared_handle_field(handle, "request_id")), prepared.action_type, prepared.payload, context)
        invocation, _authorization = self._require_prepared_unit_identity(
            request, prepared
        )
        if prepared.rejection_code is not None:
            assert prepared.rejection_message is not None
            result = self._contract_rejection_result(
                request,
                code=prepared.rejection_code,
                message=prepared.rejection_message,
                invocation=invocation,
                contract_validation=prepared.contract_validation,
            )
            return ActionReconciliationResult(
                request.action_id,
                ActionReconciliationDisposition.REJECTED,
                result,
                {
                    "contract_rejection": True,
                    "code": prepared.rejection_code,
                },
            )
        try:
            proof = self._bridge.reconcile_action(
                str(prepared_handle_field(handle, "request_id")),
                request=request,
                context=context,
                request_digest=str(prepared_handle_field(handle, "request_digest")),
                invocation_unit_digest=invocation.unit_digest,
                authorization_unit_digest=_authorization.unit_digest,
            )
        except Exception as exc:
            self._bindings.failure_log(
                "reconcile.prepared", exc, code="MINECRAFT_RECONCILIATION_FAILED"
            )
            raise MinecraftEnvironmentFailure(
                "reconcile.prepared",
                safe_exception_message(exc),
                cause_code=str(
                    getattr(exc, "cause_code", "MINECRAFT_RECONCILIATION_FAILED")
                ),
            ) from exc
        disposition = proof.disposition
        action_id = str(prepared_handle_field(handle, "request_id"))
        request_digest = str(prepared_handle_field(handle, "request_digest"))
        self._ledger.resolve(
            action_id=action_id,
            request_digest=request_digest,
            disposition=disposition,
            invocation_unit_digest=invocation.unit_digest,
            authorization_unit_digest=_authorization.unit_digest,
        )
        certainty = (
            EffectCertainty.EFFECT_CONFIRMED
            if disposition is ActionReconciliationDisposition.APPLIED
            else EffectCertainty.EFFECT_REJECTED
            if disposition is ActionReconciliationDisposition.REJECTED
            else EffectCertainty.NO_EFFECT
            if disposition is ActionReconciliationDisposition.NOT_APPLIED
            else EffectCertainty.INDETERMINATE
        )
        accepted = disposition is ActionReconciliationDisposition.APPLIED
        receipt = EffectReceipt(
            effect_id=f"minecraft-action:{action_id}",
            request_digest=request_digest,
            effect_class=_minecraft_action_effect_class(prepared.action_type),
            certainty=certainty,
            provider_instance_id=self._provider_instance_id,
            provider_receipt=action_id,
        )
        result = ActionResult(
            action_id=action_id,
            accepted=accepted,
            observation=None,
            effect=receipt,
            diagnostics={
                "environment": "minecraft",
                "action_type": prepared.action_type,
                "reconciliation": disposition.value,
            },
        )
        return ActionReconciliationResult(
            action_id, disposition, result, dict(proof.diagnostics)
        )

    def reconcile(
        self, effect: EffectReceipt, context: ExecutionContext
    ) -> EffectReceipt:
        action_id = effect.provider_receipt
        if not action_id:
            raise MinecraftEnvironmentFailure(
                "reconcile", "effect has no provider action identity"
            )
        if effect.provider_instance_id != self._provider_instance_id:
            raise ActionIdentityViolation(
                "Minecraft effect belongs to another environment provider"
            )
        verification = self._ledger.get(action_id)
        if verification is not None and verification.request_digest != effect.request_digest:
            raise ActionIdentityViolation(
                "Minecraft effect request digest does not match the action ledger"
            )
        if verification is None:
            raise ActionIdentityViolation(
                "Minecraft effect has no action-ledger Unit provenance"
            )
        if (
            verification.invocation_unit_digest is None
            or verification.authorization_unit_digest is None
        ):
            # Legacy checkpoints can be decoded for audit, but their UNKNOWN
            # actions cannot safely query a provider under a new semantic cut.
            if verification.disposition is ActionReconciliationDisposition.UNKNOWN:
                return EffectReceipt(
                    effect_id=effect.effect_id,
                    request_digest=effect.request_digest,
                    effect_class=effect.effect_class,
                    certainty=EffectCertainty.INDETERMINATE,
                    provider_instance_id=effect.provider_instance_id,
                    before_artifact=effect.before_artifact,
                    after_artifact=effect.after_artifact,
                    provider_receipt=effect.provider_receipt,
                )
        if verification.disposition is ActionReconciliationDisposition.UNKNOWN:
            request = ActionRequest(action_id, "reconcile", {}, context)
            try:
                proof = self._bridge.reconcile_action(
                    action_id,
                    request=request,
                    context=context,
                    request_digest=effect.request_digest,
                    invocation_unit_digest=verification.invocation_unit_digest,
                    authorization_unit_digest=verification.authorization_unit_digest,
                )
            except Exception as exc:
                self._bindings.failure_log(
                    "reconcile", exc, code="MINECRAFT_RECONCILIATION_FAILED"
                )
                raise MinecraftEnvironmentFailure(
                    "reconcile",
                    safe_exception_message(exc),
                    cause_code=str(
                        getattr(exc, "cause_code", "MINECRAFT_RECONCILIATION_FAILED")
                    ),
                ) from exc
            disposition = proof.disposition
        else:
            disposition = verification.disposition
        self._ledger.resolve(
            action_id=action_id,
            request_digest=effect.request_digest,
            disposition=disposition,
            invocation_unit_digest=verification.invocation_unit_digest,
            authorization_unit_digest=verification.authorization_unit_digest,
        )
        certainty = (
            EffectCertainty.EFFECT_CONFIRMED
            if disposition is ActionReconciliationDisposition.APPLIED
            else EffectCertainty.EFFECT_REJECTED
            if disposition is ActionReconciliationDisposition.REJECTED
            else EffectCertainty.NO_EFFECT
            if disposition is ActionReconciliationDisposition.NOT_APPLIED
            else EffectCertainty.INDETERMINATE
        )
        return EffectReceipt(
            effect_id=effect.effect_id,
            request_digest=effect.request_digest,
            effect_class=effect.effect_class,
            certainty=certainty,
            provider_instance_id=effect.provider_instance_id,
            before_artifact=effect.before_artifact,
            after_artifact=effect.after_artifact,
            provider_receipt=effect.provider_receipt,
        )


__all__ = ["MinecraftActionCoordinator"]
