from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionIdentityViolation,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    Observation,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonValue,
    canonical_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from ..api import (
    MINECRAFT_ACTION_TYPES,
    MinecraftActionContractError,
    MinecraftActionOutcomeStatus,
    MinecraftActionResultEvidence,
    MinecraftEnvironmentSpec,
    MinecraftObservationEvent,
    minecraft_action_timeout,
    validate_minecraft_action,
)
from ..api.ports import MinecraftBridgePort
from .action_ledger import MinecraftActionLedger
from .action_recovery import MinecraftActionRecoveryCodec
from .checkpoint import MinecraftActionVerification
from .errors import MinecraftEnvironmentFailure
from .event_views import minecraft_events_payload
from .session_diagnostics import safe_exception_message


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
        refresh_entities: bool = False,
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


@dataclass(frozen=True, slots=True)
class MinecraftActionCoordinatorBindings:
    event_log: EventLogger
    failure_log: FailureLogger
    ingest_events: EventIngester
    observation: ObservationFactory
    state_payload: StatePayloadFactory
    last_observation: LastObservationFactory


class MinecraftActionCoordinator:
    """Own Minecraft action identity, execution, recovery and reconciliation."""

    def __init__(
        self,
        *,
        session_id: str,
        generation: str,
        provider_instance_id: str,
        spec: MinecraftEnvironmentSpec,
        bridge: MinecraftBridgePort,
        bindings: MinecraftActionCoordinatorBindings,
        actions: Mapping[str, MinecraftActionVerification] | None = None,
    ) -> None:
        self._session_id = session_id
        self._generation = generation
        self._provider_instance_id = provider_instance_id
        self._spec = spec
        self._bridge = bridge
        self._bindings = bindings
        self._ledger = MinecraftActionLedger(actions)

    def snapshot(self) -> dict[str, MinecraftActionVerification]:
        return self._ledger.snapshot()

    def replace(self, values: Mapping[str, MinecraftActionVerification]) -> None:
        self._ledger = MinecraftActionLedger(values)

    def __len__(self) -> int:
        return len(self._ledger)

    def act(self, request: ActionRequest) -> ActionResult:
        request_digest = self._ledger.assert_new(request)
        self._bindings.event_log(
            "act",
            "MC_ACTION_START",
            attributes={"action_id": request.action_id, "action_type": request.action_type},
            correlation_refs=(request.action_id,),
        )
        if request.action_type not in MINECRAFT_ACTION_TYPES:
            raise ValueError(f"unsupported Minecraft action type: {request.action_type}")
        try:
            payload = validate_minecraft_action(request.action_type, request.payload)
        except MinecraftActionContractError as exc:
            self._bindings.failure_log("act.contract", exc, code=exc.code)
            raise MinecraftEnvironmentFailure(
                "act.contract", safe_exception_message(exc), cause_code=exc.code
            ) from exc
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
        action_timeout_s = minecraft_action_timeout(
            request.action_type, self._spec.bridge.command_timeout_s
        )
        payload["_action_timeout_ms"] = max(1, int(action_timeout_s * 1000))
        try:
            result = self._bridge.command(
                request.action_type, payload, timeout_s=action_timeout_s
            )
        except Exception as exc:
            self._bindings.failure_log("act", exc)
            raise MinecraftEnvironmentFailure(
                "act",
                safe_exception_message(exc),
                cause_code=str(getattr(exc, "cause_code", "MINECRAFT_ACTION_FAILED")),
            ) from exc

        evidence: MinecraftActionResultEvidence | None = None
        event_payload: Mapping[str, JsonValue] = {}
        for event in result.events:
            if event.kind != "action_result":
                continue
            event_payload = event.payload
            try:
                evidence = MinecraftActionResultEvidence.from_event(
                    event,
                    expected_action_id=request.action_id,
                    expected_action_type=request.action_type,
                )
            except ValueError as exc:
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
            exc = ValueError("bridge returned no identity-bound action_result evidence")
            self._bindings.failure_log(
                "act.evidence", exc, code="MINECRAFT_ACTION_EVIDENCE_MISSING"
            )
            raise MinecraftEnvironmentFailure(
                "act.evidence",
                safe_exception_message(exc),
                cause_code="MINECRAFT_ACTION_EVIDENCE_MISSING",
            ) from exc
        self._bindings.ingest_events(
            result.events,
            phase="act",
            refresh_entities=request.action_type == "observe_entities",
        )
        verified = evidence.verified
        if result.verified is not None and result.verified is not verified:
            exc = ValueError("bridge acknowledgement and action evidence disagree")
            self._bindings.failure_log(
                "act.evidence", exc, code="MINECRAFT_ACTION_EVIDENCE_CONFLICT"
            )
            raise MinecraftEnvironmentFailure(
                "act.evidence",
                safe_exception_message(exc),
                cause_code="MINECRAFT_ACTION_EVIDENCE_CONFLICT",
            ) from exc
        accepted = bool(result.acknowledged) and (
            evidence.status is not MinecraftActionOutcomeStatus.REJECTED
        )
        if result.diagnostics.get("error"):
            accepted = False
        certainty = (
            EffectCertainty.EFFECT_CONFIRMED
            if verified is True
            else EffectCertainty.EFFECT_REJECTED
            if verified is False and not accepted
            else EffectCertainty.EFFECT_POSSIBLE
        )
        previous = self._bindings.last_observation()
        receipt = EffectReceipt(
            effect_id=f"minecraft-action:{request.action_id}",
            request_digest=request_digest,
            effect_class=EffectClass.RECONCILABLE,
            certainty=certainty,
            provider_instance_id=self._provider_instance_id,
            verification_required=verified is not True,
            before_artifact=previous.observation_id if previous else None,
            after_artifact=canonical_digest(event_payload) if event_payload else None,
            provider_receipt=request.action_id,
        )
        self._ledger.record(
            action_id=request.action_id,
            request_digest=request_digest,
            accepted=accepted,
            verified=verified,
        )
        self._bindings.event_log(
            "act",
            "MC_ACTION_END",
            level="INFO" if accepted else "WARNING",
            attributes={
                "action_id": request.action_id,
                "action_type": request.action_type,
                "verified": verified,
                "accepted": accepted,
            },
            correlation_refs=(request.action_id,),
        )
        observation = self._bindings.observation(
            payload={
                "kind": "minecraft_action_result",
                "action_id": request.action_id,
                "action_type": request.action_type,
                "verified": verified,
                "events": minecraft_events_payload(result.events),
                "bridge_diagnostics": dict(result.diagnostics),
                **self._bindings.state_payload(),
            }
        )
        return ActionResult(
            action_id=request.action_id,
            accepted=accepted,
            observation=observation,
            effect=receipt,
            diagnostics={
                "environment": "minecraft",
                "action_type": request.action_type,
                "verified": verified,
                "bridge_acknowledged": result.acknowledged,
            },
        )

    def prepare_action_recovery(
        self, request: ActionRequest, context: ExecutionContext
    ) -> PreparedEffectHandle:
        if request.context != context:
            raise ActionIdentityViolation("Minecraft prepared action context mismatch")
        if request.action_type not in MINECRAFT_ACTION_TYPES:
            raise ValueError(f"unsupported Minecraft action type: {request.action_type}")
        try:
            validate_minecraft_action(request.action_type, request.payload)
        except MinecraftActionContractError as exc:
            raise MinecraftEnvironmentFailure(
                "act.prepare", safe_exception_message(exc), cause_code=exc.code
            ) from exc
        return MinecraftActionRecoveryCodec.prepare(
            request,
            session_id=self._session_id,
            generation=self._generation,
            provider_instance_id=self._provider_instance_id,
        )

    def execute_prepared_action(
        self, request: ActionRequest, handle: PreparedEffectHandle
    ) -> ActionResult:
        MinecraftActionRecoveryCodec.require_request(
            request,
            handle,
            session_id=self._session_id,
            generation=self._generation,
            provider_instance_id=self._provider_instance_id,
        )
        return self.act(request)

    def reconcile_prepared_action(
        self, handle: PreparedEffectHandle, context: ExecutionContext
    ) -> ActionReconciliationResult:
        prepared = MinecraftActionRecoveryCodec.decode(
            handle,
            session_id=self._session_id,
            generation=self._generation,
            provider_instance_id=self._provider_instance_id,
        )
        request = ActionRequest(handle.request_id, prepared.action_type, prepared.payload, context)
        try:
            proof = self._bridge.reconcile_action(
                handle.request_id,
                request=request,
                context=context,
                request_digest=handle.request_digest,
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
        if disposition is ActionReconciliationDisposition.UNKNOWN:
            return ActionReconciliationResult(
                handle.request_id, disposition, None, dict(proof.diagnostics)
            )
        certainty = (
            EffectCertainty.EFFECT_CONFIRMED
            if disposition is ActionReconciliationDisposition.APPLIED
            else EffectCertainty.EFFECT_REJECTED
            if disposition is ActionReconciliationDisposition.REJECTED
            else EffectCertainty.NO_EFFECT
        )
        accepted = disposition is ActionReconciliationDisposition.APPLIED
        receipt = EffectReceipt(
            effect_id=f"minecraft-action:{handle.request_id}",
            request_digest=handle.request_digest,
            effect_class=EffectClass.RECONCILABLE,
            certainty=certainty,
            provider_instance_id=self._provider_instance_id,
            verification_required=False,
            provider_receipt=handle.request_id,
        )
        result = ActionResult(
            action_id=handle.request_id,
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
            handle.request_id, disposition, result, dict(proof.diagnostics)
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
        if verification is None or (
            verification.verified is not True
            and not (verification.verified is False and not verification.accepted)
        ):
            request = ActionRequest(action_id, "reconcile", {}, context)
            try:
                proof = self._bridge.reconcile_action(
                    action_id,
                    request=request,
                    context=context,
                    request_digest=effect.request_digest,
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
        elif verification.verified is True:
            disposition = ActionReconciliationDisposition.APPLIED
        else:
            disposition = ActionReconciliationDisposition.NOT_APPLIED
        if disposition is ActionReconciliationDisposition.UNKNOWN:
            self._bindings.failure_log(
                "reconcile",
                RuntimeError("external action proof is unknown"),
                code="MINECRAFT_ACTION_PROOF_UNKNOWN",
            )
            raise MinecraftEnvironmentFailure(
                "reconcile",
                "bridge cannot prove whether the external action was applied",
                cause_code="MINECRAFT_ACTION_PROOF_UNKNOWN",
            )
        certainty = (
            EffectCertainty.EFFECT_CONFIRMED
            if disposition is ActionReconciliationDisposition.APPLIED
            else EffectCertainty.EFFECT_REJECTED
            if disposition is ActionReconciliationDisposition.REJECTED
            else EffectCertainty.NO_EFFECT
        )
        return EffectReceipt(
            effect_id=effect.effect_id,
            request_digest=effect.request_digest,
            effect_class=effect.effect_class,
            certainty=certainty,
            provider_instance_id=effect.provider_instance_id,
            verification_required=False,
            before_artifact=effect.before_artifact,
            after_artifact=effect.after_artifact,
            provider_receipt=effect.provider_receipt,
        )


__all__ = ["MinecraftActionCoordinator"]
