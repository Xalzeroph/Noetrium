from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Mapping, Protocol

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    EnvironmentCapability,
    EnvironmentCapabilityDescriptor,
    EnvironmentCapabilityUnsupported,
    EnvironmentDiagnosticsPort,
    EnvironmentIdentity,
    EnvironmentImplementation,
    EnvironmentProviderCapabilities,
    EnvironmentQuery,
    EnvironmentQueryResult,
    EnvironmentSession,
    EnvironmentSessionDiagnostics,
    Observation,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.foundation.kernel.kernel import (
    EffectReceipt,
    ExecutionContext,
    JsonValue,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from noetrium_platform.foundation.kernel.unit_codec import unit_document
from noetrium_platform.foundation.kernel.kernel import thaw_json

from ..api.agent_context import minecraft_agent_context_facets
from ..api import (
    MinecraftEnvironmentRuntimeBinding,
    MinecraftObservationEvent,
    MinecraftSessionRuntimeIdentity,
    minecraft_action_catalog,
    minecraft_action_unavailable_dependencies,
    minecraft_observed_world_unit,
    minecraft_environment_abi_version,
    minecraft_environment_entity_observation_distance,
    minecraft_environment_implementation_version,
    minecraft_environment_max_entities,
    minecraft_environment_allowed_action_types,
    minecraft_environment_visible_state_fields,
    minecraft_environment_schema_version,
    normalize_minecraft_world_ops,
    require_minecraft_environment,
)
from ..api.ports import (
    MinecraftBridgePort,
    MinecraftCheckpointPort,
    MinecraftDiagnosticsPort,
    MinecraftSessionServices,
)
from .state import MinecraftStateProjection
from .checkpoint import (
    MinecraftCheckpointCodec,
    MinecraftSessionCheckpointPort,
)
from .session_diagnostics import MinecraftSessionDiagnosticRecorder, safe_exception_message
from .action_coordinator import (
    MinecraftActionCoordinator,
    MinecraftActionCoordinatorBindings,
)
from .errors import MinecraftCheckpointUnavailable, MinecraftEnvironmentFailure
from .event_views import minecraft_events_payload


class MinecraftBridgeFactory(Protocol):
    def __call__(
        self,
        environment: NoetriumUnit,
        runtime_binding: MinecraftEnvironmentRuntimeBinding,
    ) -> MinecraftBridgePort: ...


@dataclass(frozen=True, slots=True)
class MinecraftEnvironmentImplementation(EnvironmentImplementation):
    """Runtime implementation bound to one immutable Minecraft environment Unit."""

    environment: NoetriumUnit
    runtime_binding: MinecraftEnvironmentRuntimeBinding
    bridge_factory: MinecraftBridgeFactory
    checkpoint: MinecraftCheckpointPort | None = None
    checkpoint_coordinator: MinecraftSessionCheckpointPort | None = None

    def __post_init__(self) -> None:
        require_minecraft_environment(self.environment)
        if not isinstance(self.runtime_binding, MinecraftEnvironmentRuntimeBinding):
            raise TypeError("Minecraft implementation requires runtime binding")

    @property
    def identity(self) -> EnvironmentIdentity:
        environment = require_minecraft_environment(self.environment)
        return EnvironmentIdentity(
            environment_id=environment.unit_id,
            implementation_version=minecraft_environment_implementation_version(environment),
            abi_version=minecraft_environment_abi_version(environment),
            schema_version=minecraft_environment_schema_version(environment),
            artifact_digest=environment.unit_digest,
        )


class MinecraftEnvironmentSession(EnvironmentSession):
    """MC session over the bridge seam and an optional authoritative world checkpoint."""

    _CHECKPOINT_SCHEMA = MinecraftCheckpointCodec.SCHEMA

    def __init__(
        self,
        *,
        session_id: str,
        implementation: MinecraftEnvironmentImplementation,
        bridge: MinecraftBridgePort,
        diagnostics: MinecraftDiagnosticsPort | None = None,
        checkpoint_coordinator: MinecraftSessionCheckpointPort | None = None,
    ) -> None:
        if not session_id.strip():
            raise ValueError("Minecraft session_id must be non-empty")
        self.session_id = session_id
        self.implementation = implementation
        self.identity = implementation.identity
        self._provider_instance_id = f"{self.identity.environment_id}:{session_id}"
        self._visible_state_fields = minecraft_environment_visible_state_fields(
            implementation.environment
        )
        self._bridge = bridge
        self._checkpoint_coordinator = checkpoint_coordinator or MinecraftCheckpointCodec()
        self._diagnostic_recorder = MinecraftSessionDiagnosticRecorder(
            session_id=session_id,
            sink=diagnostics,
        )
        self._closed = False
        self._observation_sequence = 0
        self._restore_faulted = False
        self._projection_faulted = False
        self._last_observation: Observation | None = None
        self._state = MinecraftStateProjection(max_entities=minecraft_environment_max_entities(implementation.environment))
        self._actions = MinecraftActionCoordinator(
            session_id=session_id,
            generation=self.generation,
            provider_instance_id=self._provider_instance_id,
            command_timeout_s=implementation.runtime_binding.bridge.command_timeout_s,
            bridge=bridge,
            allowed_action_types=minecraft_environment_allowed_action_types(
                implementation.environment
            ),
            bindings=MinecraftActionCoordinatorBindings(
                event_log=self._event_log,
                failure_log=self._failure_log,
                ingest_events=self._ingest_events,
                observation=self._observation,
                state_payload=self._state_payload,
                last_observation=lambda: self._last_observation,
                decision_view=self._decision_view,
            ),
        )
        self._event_log("lifecycle", "MC_SESSION_START", level="INFO", attributes={"session_id": session_id})
        try:
            self._bridge.configure_action_recovery(self._provider_instance_id)
            self._bridge.start()
        except Exception as exc:
            self._failure_log("start", exc)
            raise MinecraftEnvironmentFailure(
                "start",
                safe_exception_message(exc),
                cause_code=str(getattr(exc, "cause_code", "MINECRAFT_BRIDGE_START_FAILED")),
            ) from exc

    @property
    def generation(self) -> str:
        return self.identity.artifact_digest

    @property
    def action_recovery_durability(self) -> str:
        durability = str(getattr(self._bridge, "action_recovery_durability", "process_local"))
        return "crash_durable" if durability == "crash_durable" else "process_local"

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Minecraft environment session is closed")
        if self._restore_faulted:
            raise RuntimeError("Minecraft environment session is unusable after restore failure")
        if self._projection_faulted:
            raise RuntimeError("Minecraft environment session is unusable after state projection failure")

    def _event_log(
        self,
        phase: str,
        event: str,
        *,
        level: str = "DEBUG",
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        self._diagnostic_recorder.event(
            phase,
            event,
            level=level,
            attributes=attributes,
            correlation_refs=correlation_refs,
        )

    def _failure_log(self, phase: str, exc: BaseException, *, code: str | None = None) -> None:
        self._diagnostic_recorder.failure(phase, exc, code=code)

    def _ingest_events(
        self,
        events: tuple[MinecraftObservationEvent, ...],
        *,
        phase: str,
    ) -> None:
        try:
            for event in events:
                self._state.ingest(event)
        except Exception as exc:
            # A batch may already have ingested earlier events before the
            # invalid one. There is no justified rollback of physical world
            # truth. Fail-close this projection/session instead of exposing a
            # partially applied causal history as an authoritative snapshot.
            self._projection_faulted = True
            self._failure_log(f"{phase}.state", exc, code="MINECRAFT_STATE_PROJECTION_FAILED")
            raise MinecraftEnvironmentFailure(
                f"{phase}.state",
                safe_exception_message(exc),
                cause_code="MINECRAFT_STATE_PROJECTION_FAILED",
            ) from exc

    def _state_payload(self) -> dict[str, JsonValue]:
        state, state_digest = self._state.snapshot_with_digest()
        return {"state": state, "state_digest": state_digest}

    def _decision_view(
        self,
        *,
        detailed_entities: bool = False,
        include_entities: bool = True,
        snapshot_state: Mapping[str, JsonValue] | None = None,
    ) -> dict[str, JsonValue]:
        return {
            "kind": "minecraft_decision_view.v1",
            "state": self._state.decision_view(
                detailed_entities=detailed_entities,
                include_entities=include_entities,
                snapshot_state=snapshot_state,
            ),
        }

    def _project_agent_state(self, state: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        allowed = self._visible_state_fields
        if allowed is None:
            return dict(state)
        return {name: value for name, value in state.items() if name in allowed}

    def _agent_observation_payload(
        self, payload: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        # One visibility cut governs every public Observation type, not just
        # the planner's text prompt. Raw events and bridge diagnostics
        # remain only in the journal/evidence authority. No per-method filter.
        if self._visible_state_fields is None:
            result = dict(payload)
            result["agent_context_format"] = "jsonl"
            raw_state = result.get("state")
            state = dict(raw_state) if isinstance(raw_state, Mapping) else {}
            raw_decision = result.get("decision_view")
            if isinstance(raw_decision, Mapping):
                decision_state = raw_decision.get("state")
                if isinstance(decision_state, Mapping) and "nearby_entities" not in decision_state:
                    state.pop("nearby_entities", None)
            result["agent_context_facets"] = minecraft_agent_context_facets(state)
            return result
        raw_state = payload.get("state")
        state = self._project_agent_state(
            raw_state if isinstance(raw_state, Mapping) else {}
        )
        result: dict[str, JsonValue] = {
            key: value for key, value in payload.items()
            if key in {
                "kind", "action_id", "action_type",
                "effect_disposition", "outcome_status"
            }
        }
        result["agent_context_format"] = "jsonl"
        result["state"] = state
        result["state_digest"] = canonical_digest(state)
        raw_decision = payload.get("decision_view")
        facet_state = state
        if isinstance(raw_decision, Mapping):
            candidate = raw_decision.get("state")
            projected_decision_state = self._project_agent_state(
                candidate if isinstance(candidate, Mapping) else {}
            )
            result["decision_view"] = {
                "kind": "minecraft_decision_view.v1",
                "state": projected_decision_state,
            }
            if "nearby_entities" not in projected_decision_state and "nearby_entities" in state:
                facet_state = dict(state)
                facet_state.pop("nearby_entities", None)
        # Preserve only the public effect certainty, never the internal
        # provider receipt. Without this the universal Context Engine cannot
        # distinguish a previous observation from a confirmed live result
        # after an indeterminate physical command.
        receipt = payload.get("effect_receipt")
        if isinstance(receipt, Mapping):
            result["effect_receipt"] = {
                key: receipt[key]
                for key in ("certainty", "effect_class")
                if key in receipt
            }
        # Project after the single visibility cut: hidden rules never
        # reappear through model-facing agent context facets.
        result["agent_context_facets"] = minecraft_agent_context_facets(facet_state)
        return result

    def _agent_action_result(self, result: ActionResult) -> ActionResult:
        if self._visible_state_fields is None:
            return result
        # In particular, provider_outcome would bypass the state restriction:
        # a provider receipt is evidence to the researcher, not automatically
        # knowledge authorized for the Agent.
        return replace(result, diagnostics={
            key: value for key, value in result.diagnostics.items()
            if key in {
                "environment", "action_type", "effect_disposition",
                "outcome_status", "bridge_acknowledged",
                "contract_rejection_code", "contract_rejection_message",
                "reconciliation", "post_reconciliation_observation_id",
                "post_reconciliation_observation_is_effect_proof",
            }
        })

    def _observation(
        self,
        *,
        payload: Mapping[str, JsonValue],
        artifact_refs: tuple[str, ...] = (),
    ) -> Observation:
        previous_observation = self._last_observation
        public_payload = self._agent_observation_payload(payload)
        self._observation_sequence += 1
        observation_id = (
            f"minecraft:{self.session_id}:observation:{self._observation_sequence}"
        )
        # Bind the same Authority-owned cut to every visible observation
        # facet. Provider declarations are not promoted to observed facts.
        facets = public_payload.get("agent_context_facets", ())
        if not isinstance(facets, (tuple, list)):
            raise TypeError("Minecraft Context facets must be ordered observations")
        public_payload["agent_context_facets"] = tuple(
            {
                **facet,
                **({
                    "evidence_ref": observation_id,
                    "validity": {
                        "observation_id": observation_id,
                        "generation": self.generation,
                        "temporal_scope": "at_observation",
                    },
                } if facet.get("truth_class") in {"observed", "evidenced"} else {}),
            }
            for facet in facets
        )
        observation = Observation(
            observation_id=observation_id,
            generation=self.generation,
            payload=public_payload,
            artifact_refs=(
                artifact_refs if self._visible_state_fields is None else ()
            ),
        )
        self._last_observation = observation
        # The observed-world Unit is a projection of legally available
        # decision context. It contains no evaluator state or inferred hidden
        # Minecraft state. The full Unit lives in the causal audit log, never
        # in the agent's observation payload.
        state_digest = public_payload.get("state_digest")
        if isinstance(state_digest, str):
            decision = public_payload.get("decision_view")
            if not isinstance(decision, Mapping):
                decision = self._decision_view()
            previous = previous_observation
            prior_view = (
                previous.payload.get("decision_view")
                if previous is not None and previous.generation == self.generation
                else None
            )
            if not isinstance(prior_view, Mapping):
                prior_view = None
            observed = minecraft_observed_world_unit(
                observation_id=observation.observation_id,
                generation=self.generation,
                state_digest=state_digest,
                decision_view=decision,
                base_observation_id=(
                    previous.observation_id if prior_view is not None else None
                ),
                base_decision_view=prior_view,
            )
            self._event_log(
                "observe",
                "MC_OBSERVED_WORLD_UNIT",
                level="INFO",
                attributes={
                    "unit_digest": observed.unit_digest,
                    "unit": thaw_json(unit_document(observed)),
                },
                correlation_refs=(observation.observation_id, observed.unit_digest),
            )
        return observation

    def observe(self, context: ExecutionContext) -> Observation:
        self._assert_open()
        self._event_log("observe", "MC_OBSERVE_START", attributes={"task_id": context.task_id})
        try:
            snapshot = self._bridge.command(
                "snapshot",
                {
                    "context": {"run_id": context.run_id, "task_id": context.task_id},
                    "include_entities": True,
                    "entity_distance": minecraft_environment_entity_observation_distance(
                        self.implementation.environment
                    ),
                    "entity_limit": minecraft_environment_max_entities(
                        self.implementation.environment
                    ),
                },
                timeout_s=self.implementation.runtime_binding.bridge.command_timeout_s,
            )
        except Exception as exc:
            self._failure_log("observe", exc)
            raise MinecraftEnvironmentFailure(
                "observe",
                safe_exception_message(exc),
                cause_code=str(getattr(exc, "cause_code", "MINECRAFT_OBSERVE_FAILED")),
            ) from exc
        events = snapshot.events
        if not any(event.kind == "entity_snapshot" for event in events):
            error = MinecraftEnvironmentFailure(
                "observe.entities",
                "snapshot returned no entity_snapshot",
                cause_code="MINECRAFT_ENTITY_OBSERVATION_UNAVAILABLE",
            )
            self._failure_log("observe.entities", error)
            raise error
        if not any(event.kind in {"self_snapshot", "spawn_snapshot"} for event in events):
            error = MinecraftEnvironmentFailure(
                "observe",
                "bridge returned no self snapshot",
                cause_code="MINECRAFT_EMPTY_OBSERVATION",
            )
            self._failure_log("observe", error)
            raise error
        self._ingest_events(snapshot.events, phase="observe")
        self._event_log("observe", "MC_OBSERVE_END", attributes={"event_count": len(events)})
        return self._observation(
            payload={
                "kind": "minecraft_snapshot",
                "events": minecraft_events_payload(events),
                "bridge_diagnostics": {"snapshot": dict(snapshot.diagnostics)},
                **(state := self._state_payload()),
                "decision_view": self._decision_view(snapshot_state=state["state"]),
            }
        )

    def wait_for_task_setup_anchor(
        self,
        *,
        timeout_s: float = 8.0,
    ) -> Mapping[str, JsonValue]:
        """Wait event-driven until the final survival body is physically supported.

        This is provider-private setup synchronization. It deliberately carries
        no benchmark target facts: the only requested projection is a live
        survival anchor, and Mineflayer re-evaluates it on physics/transport
        events rather than polling.
        """
        self._assert_open()
        if timeout_s <= 0:
            raise ValueError("Minecraft setup anchor timeout must be positive")
        result = self._bridge.command(
            "setup_verify_wait",
            {
                "setup": {"require_physical_anchor": True},
                "timeout_ms": max(1, int(round(timeout_s * 1000.0))),
            },
            timeout_s=timeout_s + 1.0,
        )
        ack = result.diagnostics.get("ack")
        if not isinstance(ack, Mapping):
            raise MinecraftEnvironmentFailure(
                "setup.anchor",
                "Mineflayer setup anchor verifier returned no structured ACK",
                cause_code="MINECRAFT_SETUP_ANCHOR_PROOF_MISSING",
            )
        proof = {
            key: value
            for key, value in ack.items()
            if key not in {"type", "protocol_version", "cmd", "request_id"}
        }
        if proof.get("verified") is True:
            proof_digest = canonical_digest(proof)
            self._event_log(
                "setup.anchor",
                "MC_TASK_SETUP_SURVIVAL_ANCHOR_VERIFIED",
                level="INFO",
                attributes={
                    "proof_digest": proof_digest,
                    "wait_mode": "event_driven",
                },
                correlation_refs=(proof_digest,),
            )
            return proof
        failures = proof.get("failures", ())
        raise MinecraftEnvironmentFailure(
            "setup.anchor",
            "Minecraft survival body did not reach a supported setup anchor",
            cause_code="MINECRAFT_SETUP_ANCHOR_NOT_CONVERGED",
            diagnostics={
                "failures": failures if isinstance(failures, (tuple, list)) else (),
                "proof": proof,
            },
        )

    def verify_task_setup(
        self,
        setup: Mapping[str, object],
        *,
        control_proof: Mapping[str, object] | None = None,
        timeout_s: float = 8.0,
    ) -> Mapping[str, JsonValue]:
        """Read back benchmark setup from the container-local Mineflayer view.

        This command is provider-internal: it is not an Agent action and never
        enters the model-visible action catalog. RCON applies setup mutations;
        the independently running Mineflayer client proves the resulting live
        world/agent state before the task is admitted.
        """
        self._assert_open()
        if not isinstance(setup, Mapping):
            raise TypeError("Minecraft task setup verification requires a mapping")
        if timeout_s <= 0:
            raise ValueError("Minecraft task setup verification timeout must be positive")

        inventory = setup.get("initial_inventory", ())
        mobs = setup.get("initial_mobs", ())
        if isinstance(inventory, (str, bytes, bytearray)) or not isinstance(inventory, (tuple, list)):
            raise TypeError("Minecraft initial_inventory must be a sequence")
        if isinstance(mobs, (str, bytes, bytearray)) or not isinstance(mobs, (tuple, list)):
            raise TypeError("Minecraft initial_mobs must be a sequence")
        projection: dict[str, JsonValue] = {
            "dimension": str(setup.get("dimension") or "overworld"),
            "weather": str(setup.get("weather") or "clear"),
            "start_at_night": bool(setup.get("start_at_night", False)),
            "initial_inventory": tuple(dict(row) for row in inventory if isinstance(row, Mapping)),
            "initial_mobs": tuple(dict(row) for row in mobs if isinstance(row, Mapping)),
            "world_ops": tuple(dict(row) for row in normalize_minecraft_world_ops(setup.get("world_ops", ()))),
        }
        biome = setup.get("biome")
        if isinstance(biome, str) and biome.strip():
            projection["biome"] = biome.strip()

        # Transport authority is derived only from the server-side control proof.
        # Never trust a benchmark payload to provide this internal synchronization
        # witness. A biome read is meaningful only after Mineflayer has converged
        # onto the same authoritative voxel as the server.
        if isinstance(control_proof, Mapping):
            checks = control_proof.get("checks", ())
            if isinstance(checks, (tuple, list)):
                for row in checks:
                    if not isinstance(row, Mapping) or row.get("kind") != "biome_authority":
                        continue
                    position = row.get("position")
                    if not isinstance(position, Mapping):
                        break
                    values: dict[str, float] = {}
                    for axis in ("x", "y", "z"):
                        value = position.get(axis)
                        if not isinstance(value, (int, float)) or isinstance(value, bool):
                            values = {}
                            break
                        numeric = float(value)
                        if not math.isfinite(numeric):
                            values = {}
                            break
                        values[axis] = numeric
                    if len(values) == 3:
                        projection["authority_position"] = values
                    break

        result = self._bridge.command(
            "setup_verify_wait",
            {
                "setup": projection,
                "timeout_ms": max(1, int(round(timeout_s * 1000.0))),
            },
            timeout_s=timeout_s + 1.0,
        )
        ack = result.diagnostics.get("ack")
        if not isinstance(ack, Mapping):
            raise MinecraftEnvironmentFailure(
                "setup.verify",
                "Mineflayer setup verifier returned no structured ACK",
                cause_code="MINECRAFT_SETUP_PROOF_MISSING",
            )
        proof = {
            key: value
            for key, value in ack.items()
            if key not in {"type", "protocol_version", "cmd", "request_id"}
        }
        if proof.get("verified") is True:
            proof_digest = canonical_digest(proof)
            self._event_log(
                "setup.verify",
                "MC_TASK_SETUP_PHYSICAL_VERIFIED",
                level="INFO",
                attributes={
                    "proof_digest": proof_digest,
                    "wait_mode": "event_driven",
                    "check_count": proof.get("check_count"),
                },
                correlation_refs=(proof_digest,),
            )
            return proof

        failures = proof.get("failures", ())
        failure_digest = canonical_digest({
            "projection": projection,
            "proof": proof,
            "wait_mode": "event_driven",
        })
        self._event_log(
            "setup.verify",
            "MC_TASK_SETUP_PHYSICAL_REJECTED",
            level="ERROR",
            attributes={
                "failure_digest": failure_digest,
                "wait_mode": "event_driven",
                "timed_out": proof.get("timed_out"),
                "failures": failures if isinstance(failures, (tuple, list)) else (),
            },
            correlation_refs=(failure_digest,),
        )
        raise MinecraftEnvironmentFailure(
            "setup.verify",
            "Minecraft task setup physical postconditions did not converge; "
            + f"failure_digest={failure_digest}; failures={str(failures)[:1200]}",
            cause_code="MINECRAFT_SETUP_POSTCONDITION_FAILED",
            diagnostics={
                "failure_digest": failure_digest,
                "timed_out": bool(proof.get("timed_out")),
                "failures": tuple(failures)
                if isinstance(failures, (tuple, list)) else (),
                "proof": proof,
            },
        )

    def _task_event(self, status: str, context: ExecutionContext) -> Observation:
        payload = {
            "task_id": str(context.task_id or ""),
            "status": status,
            "context": {
                "run_id": context.run_id,
                "study_id": context.study_id,
                "task_id": context.task_id,
            },
        }
        result = self._bridge.command(
            "task_event",
            payload,
            timeout_s=self.implementation.runtime_binding.bridge.command_timeout_s,
        )
        self._ingest_events(result.events, phase="task_event")
        return self._observation(
            payload={
                "kind": "minecraft_task_event",
                "events": minecraft_events_payload(result.events),
                "bridge_diagnostics": dict(result.diagnostics),
                **self._state_payload(),
            }
        )

    def begin_task(self, metadata: Mapping[str, JsonValue], context: ExecutionContext) -> Observation:
        self._assert_open()
        del metadata
        return self._task_event("STARTED", context)

    def end_task(self, metadata: Mapping[str, JsonValue], context: ExecutionContext) -> Observation:
        self._assert_open()
        status = str(metadata.get("status") or "ENDED")
        return self._task_event(status, context)

    def act(self, request: ActionRequest, control: ExecutionControlPort) -> ActionResult:
        self._assert_open()
        return self._agent_action_result(self._actions.act(request, control))

    def prepare_action_recovery(
        self,
        request: ActionRequest,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> NoetriumUnit:
        self._assert_open()
        return self._actions.prepare_action_recovery(request, context, control)

    def execute_prepared_action(
        self,
        request: ActionRequest,
        handle: NoetriumUnit,
        control: ExecutionControlPort,
    ) -> ActionResult:
        self._assert_open()
        return self._agent_action_result(
            self._actions.execute_prepared_action(request, handle, control)
        )

    def reconcile_prepared_action(
        self,
        handle: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> ActionReconciliationResult:
        self._assert_open()
        resolved = self._actions.reconcile_prepared_action(handle, context, control)
        if resolved.result is not None:
            resolved = replace(resolved, result=self._agent_action_result(resolved.result))
        if self._visible_state_fields is not None:
            resolved = replace(
                resolved,
                diagnostics={
                    key: value for key, value in resolved.diagnostics.items()
                    if key in {"contract_rejection", "code", "disposition"}
                },
            )
        if resolved.result is None or resolved.result.observation is not None:
            return resolved
        # Reconciliation proves only the historical action disposition. The
        # durable journal intentionally does not claim a current-world state,
        # so any recovered ActionResult without an Observation must refresh the
        # Agent context before the Method plans again. This is recovery-only:
        # the normal act() hot path still returns its existing Observation and
        # pays no extra bridge round trip. The refresh never serves as
        # retrospective effect proof, regardless of the proven disposition.
        try:
            observation = self.observe(context)
        except Exception as exc:
            self._failure_log(
                "reconcile.observe", exc,
                code="MINECRAFT_RECONCILIATION_OBSERVATION_UNAVAILABLE",
            )
            # Preserve the independently established UNKNOWN verdict even
            # when the subsequent read-only refresh is unavailable.
            return resolved
        result = replace(
            resolved.result,
            observation=observation,
            diagnostics={
                **resolved.result.diagnostics,
                "post_reconciliation_observation_id": observation.observation_id,
                "post_reconciliation_observation_is_effect_proof": False,
            },
        )
        self._event_log(
            "reconcile.observe", "MC_RECONCILIATION_WORLD_REFRESHED",
            level="INFO",
            attributes={
                "action_id": resolved.action_id,
                "observation_id": observation.observation_id,
                "disposition": resolved.disposition.value,
                "effect_proven": False,
            },
            correlation_refs=(resolved.action_id, observation.observation_id),
        )
        return replace(resolved, result=result)

    def reconcile(self, effect: EffectReceipt, context: ExecutionContext) -> EffectReceipt:
        self._assert_open()
        return self._actions.reconcile(effect, context)

    def query(self, request: EnvironmentQuery) -> EnvironmentQueryResult:
        self._assert_open()
        if request.query_type == "capabilities":
            return EnvironmentQueryResult(
                request.query_id,
                True,
                {
                    "environment": "minecraft",
                    "generation": self.generation,
                    "capabilities": [
                        {
                            "capability_id": descriptor.capability_id,
                            "version": descriptor.version,
                            "action_types": list(descriptor.action_types),
                            "query_types": list(descriptor.query_types),
                            "metadata": descriptor.metadata,
                        }
                        for descriptor in self.capability_descriptors()
                    ],
                },
                self._last_observation,
            )
        if request.query_type == "state":
            # A state query returns the exact visibility-cut state, not a
            # second context/prompt projection. The already available
            # observation carries source-typed context facets.
            state, digest = self._state.snapshot_with_digest()
            visible = self._project_agent_state(state)
            return EnvironmentQueryResult(
                request.query_id,
                True,
                {
                    "state": visible,
                    "state_digest": (
                        digest if self._visible_state_fields is None
                        else canonical_digest(visible)
                    ),
                },
                self._last_observation,
            )
        if request.query_type == "entity":
            if (
                self._visible_state_fields is not None
                and "nearby_entities" not in self._visible_state_fields
            ):
                raise EnvironmentCapabilityUnsupported("query:entity")
            query = str(request.payload.get("name", "")).lower() if isinstance(request.payload, Mapping) else ""
            rows = (value.compact() for value in self._state.entities.values())
            entities = [
                row for row in rows
                if not query or query in str(row).lower()
            ]
            return EnvironmentQueryResult(
                request.query_id,
                True,
                {"entities": entities, "count": len(entities)},
                self._last_observation,
            )
        if request.query_type == "task":
            return EnvironmentQueryResult(
                request.query_id,
                True,
                {
                    "opaque_task_ref": (
                        None if request.context.task_id is None
                        else "task:" + canonical_digest({
                            "task_id": request.context.task_id
                        })[:20]
                    ),
                    "state_digest": (
                        self._state.snapshot_digest()
                        if self._visible_state_fields is None
                        else canonical_digest(
                            self._project_agent_state(self._state.compact())
                        )
                    ),
                },
                self._last_observation,
            )
        raise EnvironmentCapabilityUnsupported(f"query:{request.query_type}")

    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]:
        allowed = minecraft_environment_allowed_action_types(self.implementation.environment)
        executable = tuple(
            contract for contract in minecraft_action_catalog()
            if contract.action_type in allowed
            and not minecraft_action_unavailable_dependencies(contract.action_type, allowed)
        )
        # Model and user-facing capability discovery must match the same
        # authorization closure enforced by the root action coordinator.
        return (
            EnvironmentCapabilityDescriptor(
                capability_id="minecraft.world",
                version=minecraft_environment_schema_version(self.implementation.environment),
                action_types=tuple(contract.action_type for contract in executable),
                query_types=(
                    ("capabilities", "state", "entity", "task")
                    if self._visible_state_fields is None
                    or "nearby_entities" in self._visible_state_fields
                    else ("capabilities", "state", "task")
                ),
                metadata={
                    "bridge": "replaceable",
                    "minimum_action_execution_seconds": (
                        self._actions.minimum_action_execution_seconds
                    ),
                    # The Environment Provider, not the Method, selects the
                    # read-only action that creates an initial visibility cut.
                    # No task, recipe, or hidden rule is exposed here.
                    "initial_observation_action": {
                        "action_type": "observe_blocks",
                        "arguments": {},
                    },
                    "max_entities": minecraft_environment_max_entities(self.implementation.environment),
                    "state_digest": (
                        self._state.snapshot_digest()
                        if self._visible_state_fields is None
                        else canonical_digest(
                            self._project_agent_state(self._state.compact())
                        )
                    ),
                    "action_contracts": tuple(
                        contract.as_payload() for contract in executable
                    ),
                },
            ),
        )

    def checkpoint(self) -> bytes:
        self._assert_open()
        provider = self.implementation.checkpoint
        if provider is None:
            self._event_log("checkpoint", "MC_CHECKPOINT_UNAVAILABLE", level="WARNING")
            raise MinecraftCheckpointUnavailable(
                "Minecraft session has no authoritative world checkpoint provider"
            )
        try:
            payload, world_bytes = self._checkpoint_coordinator.capture(
                provider=provider,
                session_id=self.session_id,
                generation=self.generation,
                observation_sequence=self._observation_sequence,
                actions=self._actions.snapshot(),
                state=self._state,
                last_observation=self._last_observation,
            )
        except Exception as exc:
            self._failure_log("checkpoint", exc, code="MINECRAFT_CHECKPOINT_CAPTURE_FAILED")
            raise
        self._event_log(
            "checkpoint",
            "MC_CHECKPOINT_CAPTURED",
            level="INFO",
            attributes={"bytes": len(payload), "world_bytes": world_bytes},
        )
        return payload

    def restore(self, payload: bytes) -> None:
        self._assert_open()
        provider = self.implementation.checkpoint
        if provider is None:
            self._event_log("restore", "MC_RESTORE_UNAVAILABLE", level="WARNING")
            raise MinecraftCheckpointUnavailable(
                "Minecraft session has no authoritative world checkpoint provider"
            )
        try:
            restored = self._checkpoint_coordinator.decode(
                payload,
                session_id=self.session_id,
                generation=self.generation,
                max_entities=minecraft_environment_max_entities(self.implementation.environment),
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, UnicodeError) as exc:
            self._failure_log("restore.decode", exc, code="MINECRAFT_CHECKPOINT_INVALID")
            raise MinecraftEnvironmentFailure(
                "restore.decode",
                safe_exception_message(exc),
                cause_code="MINECRAFT_CHECKPOINT_INVALID",
            ) from exc

        bridge_stopped = False
        try:
            self._bridge.close()
            bridge_stopped = True
            provider.restore(restored.world_payload, session_id=self.session_id, context=None)
            self._bridge.start()
            bridge_stopped = False
        except Exception as exc:
            self._restore_faulted = True
            recovery_error: BaseException | None = None
            if bridge_stopped:
                try:
                    self._bridge.start()
                except BaseException as recovery_exc:
                    recovery_error = recovery_exc
            detail = safe_exception_message(exc)
            if recovery_error is not None:
                detail += (
                    "; bridge recovery failed: "
                    f"{safe_exception_message(recovery_error)}"
                )
            self._failure_log("restore", exc, code="MINECRAFT_CHECKPOINT_RESTORE_FAILED")
            raise MinecraftEnvironmentFailure(
                "restore",
                detail,
                cause_code="MINECRAFT_CHECKPOINT_RESTORE_FAILED",
                diagnostics={
                    "bridge_recovery_failed": recovery_error is not None,
                },
            ) from exc
        self._state = restored.state
        self._observation_sequence = restored.observation_sequence
        self._actions.replace(restored.actions)
        self._last_observation = restored.last_observation
        self._event_log(
            "restore",
            "MC_CHECKPOINT_RESTORED",
            level="INFO",
            attributes={"bytes": len(payload), "world_bytes": len(restored.world_payload)},
        )

    def diagnostics_snapshot(self) -> EnvironmentSessionDiagnostics:
        supported = [
            EnvironmentCapability.DIAGNOSTICS,
            EnvironmentCapability.RECONCILE,
            EnvironmentCapability.QUERY,
        ]
        if self.implementation.checkpoint is not None:
            supported.extend((EnvironmentCapability.SNAPSHOT, EnvironmentCapability.RESTORE))
        return EnvironmentSessionDiagnostics(
            session_id=self.session_id,
            environment=self.identity,
            generation=self.generation,
            ready=not self._closed and not self._restore_faulted and not self._projection_faulted,
            closed=self._closed,
            capabilities=EnvironmentProviderCapabilities(tuple(supported)),
            state_digest=self._state.snapshot_digest(),
        )

    def diagnostics(self) -> dict[str, object]:
        return {
            "environment": "minecraft",
            "session_id": self.session_id,
            "generation": self.generation,
            "closed": self._closed,
            "observation_sequence": self._observation_sequence,
            "known_action_ids": len(self._actions),
            "diagnostic_sink_failures": self._diagnostic_recorder.sink_failures,
            "restore_faulted": self._restore_faulted,
            "projection_faulted": self._projection_faulted,
            "checkpoint_provider": self.implementation.checkpoint is not None,
            "state_digest": self._state.snapshot_digest(),
            "state_last_event_sequence": self._state.last_event_sequence,
            "state_entity_count": len(self._state.entities),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._event_log("lifecycle", "MC_SESSION_CLOSE", level="INFO")
        try:
            self._bridge.close()
        except Exception as exc:
            self._failure_log("close", exc, code="MINECRAFT_BRIDGE_CLOSE_FAILED")
            raise MinecraftEnvironmentFailure(
                "close",
                safe_exception_message(exc),
                cause_code="MINECRAFT_BRIDGE_CLOSE_FAILED",
            ) from exc
        self._closed = True


class MinecraftEnvironmentRuntime:
    """Session lifecycle owner; it does not own MC semantics or server lifecycle."""

    RUNTIME_ID = "minecraft.environment.session"
    RUNTIME_VERSION = "2"
    RUNTIME_ABI_VERSION = "1"

    def __init__(
        self,
        bridge_factory: MinecraftBridgeFactory,
        *,
        diagnostics: MinecraftDiagnosticsPort | None = None,
    ) -> None:
        self._bridge_factory = bridge_factory
        self._diagnostics = diagnostics
        self._runtime_identity = MinecraftSessionRuntimeIdentity(
            self.RUNTIME_ID,
            self.RUNTIME_VERSION,
            self.RUNTIME_ABI_VERSION,
            canonical_digest(
                {
                    "runtime_id": self.RUNTIME_ID,
                    "runtime_version": self.RUNTIME_VERSION,
                    "runtime_abi_version": self.RUNTIME_ABI_VERSION,
                    "session_contract": MinecraftEnvironmentSession._CHECKPOINT_SCHEMA,
                }
            ),
        )

    @property
    def runtime_identity(self) -> MinecraftSessionRuntimeIdentity:
        return self._runtime_identity

    def open_session(
        self,
        implementation: MinecraftEnvironmentImplementation,
        *,
        session_id: str,
        services: MinecraftSessionServices,
    ) -> MinecraftEnvironmentSession:
        del services
        if not isinstance(implementation, MinecraftEnvironmentImplementation):
            raise TypeError(
                "MinecraftEnvironmentRuntime requires "
                "MinecraftEnvironmentImplementation"
            )
        bridge = self._bridge_factory(
            implementation.environment,
            implementation.runtime_binding,
        )
        return MinecraftEnvironmentSession(
            session_id=session_id,
            implementation=implementation,
            bridge=bridge,
            diagnostics=self._diagnostics,
            checkpoint_coordinator=implementation.checkpoint_coordinator,
        )


__all__ = [
    "MinecraftBridgeFactory",
    "MinecraftCheckpointUnavailable",
    "MinecraftEnvironmentFailure",
    "MinecraftEnvironmentImplementation",
    "MinecraftEnvironmentRuntime",
    "MinecraftEnvironmentSession",
]
