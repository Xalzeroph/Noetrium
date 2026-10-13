from __future__ import annotations

from collections import deque
import hashlib
import math
import json
from pathlib import Path
from threading import Lock
import time
from typing import Mapping
from uuid import uuid4

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    ActionIdentityViolation,
    ActionRequest,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort, TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue
from noetrium_platform.foundation.kernel.record import record_payload
from noetrium_platform.substrate.api import OperatingSystemRoute, ProcessSupervisorPort

from ..api import (
    MINECRAFT_ACTION_TYPES,
    MinecraftBridgeCommandResult,
    MinecraftBridgeEnvelope,
    MinecraftBridgePort,
    MinecraftBridgeSpec,
    MinecraftActionOutcomeStatus,
    minecraft_action_result_record,
    MinecraftAgentSpec,
    MinecraftDiagnosticsPort,
    MinecraftEndpointSpec,
    MinecraftObservationEvent,
    MinecraftReconciliation,
)
from .jsonl_transport import (
    JsonlBridgeMessage,
    JsonlProcess,
    JsonlProcessTransport,
    MinecraftBridgeError,
    ProcessFactory,
    safe_exception_message,
)


class JsonlMinecraftBridge(MinecraftBridgePort):
    """Mineflayer-independent JSONL transport extracted from v034.

    The class owns only the short-lived bridge transport. A Minecraft Java
    server is not started, stopped or inferred here. A process factory is
    injectable so the protocol can be tested without Node or Minecraft.
    """

    def __init__(
        self,
        *,
        endpoint: MinecraftEndpointSpec,
        spec: MinecraftBridgeSpec,
        agent: MinecraftAgentSpec,
        operating_system: OperatingSystemRoute,
        process_factory: ProcessFactory | None = None,
        process_supervisor: ProcessSupervisorPort,
        diagnostics: MinecraftDiagnosticsPort | None = None,
        task_group: TaskGroupPort,
        stderr_tail_lines: int = 300,
    ) -> None:
        self.endpoint = endpoint
        self.spec = spec
        self.agent = agent
        self._diagnostics = diagnostics
        self._diagnostic_errors: deque[str] = deque(maxlen=20)
        self._request_counter = 0
        self._action_proofs: dict[str, ActionReconciliationDisposition] = {}
        self._action_proof_digests: dict[str, str] = {}
        self._action_request_digests: dict[str, str] = {}
        self._action_unit_lineage: dict[str, tuple[str, str]] = {}
        # Retain unresolved action identities when an ACK is lost. This is a
        # fail-closed uncertainty fence, not an independent effect authority.
        self._unacknowledged_actions: set[str] = set()
        actor_identity = hashlib.sha256(
            f"{endpoint.host}:{endpoint.bound_port}:{agent.username}".encode("utf-8")
        ).hexdigest()[:20]
        self._task_group = task_group
        self._bridge_identity = actor_identity
        self._action_recovery_root = (
            Path(self.spec.action_recovery_root)
            if self.spec.action_recovery_root is not None
            else None
        )
        self._action_recovery_dir: Path | None = None
        self._transport = JsonlProcessTransport(
            spec=spec,
            operating_system=operating_system,
            task_group=task_group,
            bridge_identity=actor_identity,
            process_factory=process_factory,
            process_supervisor=process_supervisor,
            failure_reporter=self._failure_log,
            stderr_tail_lines=stderr_tail_lines,
        )
        self._operation_lock = Lock()
        self._closing = False
        self._recycle_pending = False
        self._event_stream_id: str | None = None
        self._terminal_settlement_timeout_s: float | None = None
        # Control-plane prepare/reconcile commands share the same ordered bridge
        # stream as world events.  They must never consume asynchronous world
        # evidence (death, respawn, weather, etc.) and then discard it merely
        # because their public API returns no observation.
        self._deferred_observation_events: deque[MinecraftObservationEvent] = deque()

    def _call_owned(self, operation: str, fn, /, *args):
        """Serialize the synchronous bridge API without occupying a SERIAL worker.

        The bridge protocol is deliberately synchronous at this boundary. Long
        subprocess pipe drains remain owned by the capability ASYNC_IO task group;
        a local mutex provides per-bridge ordering without pinning an external-I/O
        wait to the shared SERIAL worker pool.
        """
        del operation
        with self._operation_lock:
            return fn(*args)

    @property
    def action_recovery_durability(self) -> str:
        return "crash_durable" if self._action_recovery_root is not None else "process_local"

    @property
    def terminal_settlement_timeout_s(self) -> float:
        value = self._terminal_settlement_timeout_s
        if value is None:
            raise MinecraftBridgeError(
                "lifecycle",
                "BRIDGE_TERMINAL_SETTLEMENT_UNDECLARED",
                "bridge has not declared its terminal settlement budget",
            )
        return value

    def configure_action_recovery(self, namespace: str) -> None:
        if not namespace.strip():
            raise ValueError("Minecraft action recovery namespace must be non-empty")
        if self._transport.started:
            raise MinecraftBridgeError(
                "recovery", "BRIDGE_ALREADY_STARTED", "action recovery must be bound before start"
            )
        if self._action_recovery_root is None:
            self._action_recovery_dir = None
            return
        digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        self._action_recovery_dir = self._action_recovery_root / digest

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return self._transport.stderr_tail

    @property
    def process_id(self) -> int | None:
        return self._transport.process_id

    def supports_command(self, command: str) -> bool:
        return command in MINECRAFT_ACTION_TYPES | {
            "snapshot",
            "task_event",
            "setup_verify",
            "setup_verify_wait",
            "quit",
            "prepare_action",
            "reconcile_action",
        }

    def _event_log(
        self,
        *,
        phase: str,
        event: str,
        attributes: Mapping[str, JsonValue] | None = None,
        level: str = "DEBUG",
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.event(
                phase=phase,
                event=event,
                attributes=attributes or {},
                level=level,
                correlation_refs=correlation_refs,
            )
        except BaseException as exc:
            self._diagnostic_errors.append(f"event:{type(exc).__name__}:{exc}")

    def _failure_log(
        self,
        *,
        phase: str,
        code: str,
        message: str,
        exception: BaseException | None = None,
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.failure(
                phase=phase,
                code=code,
                message=message,
                exception=exception,
                attributes=attributes or {},
                correlation_refs=correlation_refs,
            )
        except BaseException as exc:
            self._diagnostic_errors.append(f"failure:{type(exc).__name__}:{exc}")

    def _metric(self, *, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.metric(name=name, value=value, labels=labels or {})
        except BaseException as exc:
            self._diagnostic_errors.append(f"metric:{type(exc).__name__}:{exc}")

    def _next_request_id(self, command: str, payload: Mapping[str, JsonValue]) -> str:
        candidate = payload.get("request_id") or payload.get("action_id")
        if candidate is not None and str(candidate).strip():
            return str(candidate)
        self._request_counter += 1
        return f"mc-{command}-{self._request_counter}-{uuid4().hex[:8]}"

    def _event(self, message: JsonlBridgeMessage) -> MinecraftObservationEvent:
        if message.kind != "event":
            raise MinecraftBridgeError("decode", "BRIDGE_UNEXPECTED_MESSAGE", message.kind)
        stream_id = self._event_stream_id
        if stream_id is None:
            raise MinecraftBridgeError(
                "decode",
                "BRIDGE_EVENT_WITHOUT_STREAM",
                "bridge event arrived before transport stream identity was established",
            )
        try:
            return MinecraftBridgeEnvelope.from_mapping(message.value).as_observation(
                stream_id=stream_id
            )
        except (TypeError, ValueError) as exc:
            raise MinecraftBridgeError("decode", "BRIDGE_INVALID_EVENT", safe_exception_message(exc)) from exc

    def _record_action_proof(
        self,
        action_id: str,
        disposition: ActionReconciliationDisposition,
        *,
        source: str,
        request_digest: str,
    ) -> None:
        """Monotonically refine effect truth for one exact action request.

        A disposition without its request digest is not authoritative enough to
        fence a later request. UNKNOWN may converge to terminal truth; an
        identity-bound terminal proof is immutable and contradictory evidence
        is surfaced rather than resolved by last-writer-wins.
        """
        if (
            len(request_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in request_digest)
        ):
            raise MinecraftBridgeError(
                "reconcile",
                "BRIDGE_INVALID_ACTION_PROOF_IDENTITY",
                f"action_id={action_id}; source={source}",
            )
        prior = self._action_proofs.get(action_id)
        prior_digest = self._action_proof_digests.get(action_id)
        if prior is None or prior_digest is None:
            # An unbound historical/cache value is not evidence for this exact
            # request. The first identity-bound proof replaces it.
            self._action_proofs[action_id] = disposition
            self._action_proof_digests[action_id] = request_digest
            return
        if prior_digest != request_digest:
            raise ActionIdentityViolation(
                "Minecraft action proof belongs to a different request digest"
            )
        if prior is ActionReconciliationDisposition.UNKNOWN:
            self._action_proofs[action_id] = disposition
            return
        if disposition is ActionReconciliationDisposition.UNKNOWN or disposition is prior:
            return
        raise MinecraftBridgeError(
            "reconcile",
            "BRIDGE_CONTRADICTORY_ACTION_PROOF",
            (
                f"action_id={action_id}; prior={prior.value}; "
                f"observed={disposition.value}; source={source}"
            ),
        )

    def _record_action_result_event(
        self,
        event: MinecraftObservationEvent,
        *,
        expected_action_id: str | None = None,
        expected_action_type: str | None = None,
    ) -> tuple[str, str, dict[str, JsonValue] | None]:
        """Validate one action-result independently of the currently awaited command.

        Action results can arrive after their originating synchronous call has
        already timed out/cancelled. Correlation therefore precedes ownership:
        a structurally valid late result is still authoritative reconciliation
        evidence for its own action, but must not poison the next command.
        """

        payload = event.payload
        raw_action_id = payload.get("action_id")
        action = payload.get("action")
        raw_action_type = action.get("tool") if isinstance(action, Mapping) else None
        if not isinstance(raw_action_id, str) or not raw_action_id.strip():
            raise MinecraftBridgeError(
                "decode",
                "BRIDGE_INVALID_ACTION_RESULT",
                "action_result action_id must be non-empty text",
            )
        if not isinstance(raw_action_type, str) or not raw_action_type.strip():
            raise MinecraftBridgeError(
                "decode",
                "BRIDGE_INVALID_ACTION_RESULT",
                "action_result action.tool must be non-empty text",
            )
        if event.request_id is not None and event.request_id != raw_action_id:
            raise MinecraftBridgeError(
                "decode",
                "BRIDGE_INVALID_ACTION_RESULT",
                "action_result request_id does not match payload action_id",
            )

        action_id = expected_action_id or raw_action_id
        action_type = expected_action_type or raw_action_type
        request_digest = self._action_request_digests.get(action_id)
        unit_lineage = self._action_unit_lineage.get(action_id)
        if request_digest is None or unit_lineage is None:
            raise MinecraftBridgeError(
                "decode",
                "BRIDGE_UNBOUND_ACTION_RESULT",
                f"action_result has no bound Unit request identity: {action_id}",
            )
        try:
            evidence = minecraft_action_result_record(
                event,
                expected_action_id=action_id,
                expected_action_type=action_type,
                expected_request_digest=request_digest,
                expected_invocation_unit_digest=unit_lineage[0],
                expected_authorization_unit_digest=unit_lineage[1],
            )
        except (TypeError, ValueError) as exc:
            raise MinecraftBridgeError(
                "decode",
                "BRIDGE_INVALID_ACTION_RESULT",
                safe_exception_message(exc),
            ) from exc

        evidence_payload = record_payload(evidence)
        recorded_action_id = str(evidence_payload["action_id"])
        self._record_action_proof(
            recorded_action_id,
            ActionReconciliationDisposition(str(evidence_payload["effect_disposition"])),
            source="action_result_event",
            request_digest=request_digest,
        )

        bridge_memory: dict[str, JsonValue] | None = None
        raw_bridge_memory = event.payload.get("bridge_memory")
        if raw_bridge_memory is not None:
            if not isinstance(raw_bridge_memory, Mapping):
                raise MinecraftBridgeError(
                    "decode",
                    "BRIDGE_INVALID_MEMORY_TELEMETRY",
                    "action_result bridge_memory must be a mapping",
                )
            bridge_memory = dict(raw_bridge_memory)
        return recorded_action_id, raw_action_type, bridge_memory

    def _observe_until_ack(
        self,
        *,
        command: str,
        request_id: str,
        timeout_s: float,
        require_ack: bool = True,
        control: ExecutionControlPort | None = None,
    ) -> MinecraftBridgeCommandResult:
        deadline = time.monotonic() + timeout_s
        events: list[MinecraftObservationEvent] = []
        ack: Mapping[str, JsonValue] | None = None
        bridge_memory: dict[str, JsonValue] | None = None
        while time.monotonic() < deadline:
            try:
                message = self._transport.read(
                    timeout_s=max(0.001, deadline - time.monotonic()),
                    control=control,
                )
            except BaseException:
                # The previous command may still execute in the Node process.
                # Never reuse a potentially overlapping physical-effect lane
                # after losing its correlated ACK. The caller sees UNKNOWN and
                # the bridge is recycled only at the next owned boundary.
                self._recycle_pending = True
                raise
            if message.kind == "event":
                event = self._event(message)
                if event.kind in {"error", "kicked", "end"}:
                    # Mineflayer has already declared the Minecraft connection
                    # unusable. Waiting for the command ACK after this event can
                    # only burn the remaining semantic deadline because that ACK
                    # belongs to the terminated connection. Fence the provider
                    # generation immediately; the caller preserves physical
                    # effect uncertainty and recycles at the next owned boundary.
                    self._recycle_pending = True
                    self._failure_log(
                        phase="command",
                        code="MINECRAFT_CONNECTION_TERMINATED",
                        message=f"command={command}; event={event.kind}",
                        attributes={
                            "request_id": request_id,
                            "event_payload": dict(event.payload),
                            "process_id": self.process_id,
                        },
                        correlation_refs=(request_id,),
                    )
                    raise MinecraftBridgeError(
                        "command",
                        "MINECRAFT_CONNECTION_TERMINATED",
                        (
                            f"command={command}; request_id={request_id}; "
                            f"event={event.kind}; payload={dict(event.payload)}"
                        ),
                    )
                if event.kind == "action_result":
                    raw_action_id = event.payload.get("action_id")
                    correlated = (
                        isinstance(raw_action_id, str)
                        and raw_action_id == request_id
                        and (event.request_id is None or event.request_id == request_id)
                    )
                    recorded_action_id, recorded_action_type, memory = (
                        self._record_action_result_event(
                            event,
                            expected_action_id=request_id if correlated else None,
                            expected_action_type=command if correlated else None,
                        )
                    )
                    if correlated:
                        events.append(event)
                        if memory is not None:
                            bridge_memory = memory
                    else:
                        # A late provider completion belongs to its original
                        # action. Keep the reconciliation proof, but do not
                        # contaminate the currently awaited command's evidence.
                        self._event_log(
                            phase="command",
                            event="BRIDGE_STALE_ACTION_RESULT_ROUTED",
                            level="INFO",
                            attributes={
                                "awaited_command": command,
                                "awaited_request_id": request_id,
                                "action_id": recorded_action_id,
                                "action_type": recorded_action_type,
                                "event_request_id": event.request_id,
                            },
                            correlation_refs=(recorded_action_id, request_id),
                        )
                        self._metric(
                            name="minecraft.bridge.stale_action_result",
                            value=1.0,
                            labels={
                                "awaited_command": command,
                                "action_type": recorded_action_type,
                            },
                        )
                    continue
                events.append(event)
                continue
            if message.kind != "ack":
                continue
            if str(message.value.get("cmd", "")) != command:
                continue
            observed_request_id = message.value.get("request_id")
            if not isinstance(observed_request_id, str) or observed_request_id != request_id:
                continue
            ack = message.value
            break

        if require_ack and ack is None:
            self._recycle_pending = True
            self._failure_log(
                phase="command",
                code="BRIDGE_COMMAND_TIMEOUT",
                message=f"command={command}; request_id={request_id}",
                attributes={"stderr_tail": self._transport.stderr_tail_text()},
                correlation_refs=(request_id,),
            )
            raise MinecraftBridgeError(
                "command",
                "BRIDGE_COMMAND_TIMEOUT",
                f"command={command}; request_id={request_id}; stderr_tail={self._transport.stderr_tail_text()}",
            )
        ack_value = dict(ack or {})
        verified = ack_value.get("verified")
        if verified is not None and not isinstance(verified, bool):
            raise MinecraftBridgeError(
                "decode", "BRIDGE_INVALID_ACK", "ack verified must be boolean"
            )
        rejected = ack_value.get("rejected")
        if rejected is not None and not isinstance(rejected, bool):
            raise MinecraftBridgeError(
                "decode", "BRIDGE_INVALID_ACK", "ack rejected must be boolean"
            )
        recycle_recommended = ack_value.get("bridge_recycle_recommended")
        if recycle_recommended is not None and not isinstance(recycle_recommended, bool):
            raise MinecraftBridgeError(
                "decode",
                "BRIDGE_INVALID_ACK",
                "ack bridge_recycle_recommended must be boolean",
            )
        if recycle_recommended is True:
            # The current command must return to the durable effect pipeline before
            # the bridge transport is recycled. Killing the provider before the
            # caller records RESULT_RECORDED can strand the effect in PREPARED.
            self._recycle_pending = True
        diagnostics = {
            "request_id": request_id,
            "event_count": len(events),
            "ack": ack_value,
            "stderr_tail": self.stderr_tail,
            "process_id": self.process_id,
            "error": ack_value.get("error"),
            "diagnostic_errors": tuple(self._diagnostic_errors),
            "bridge_memory": bridge_memory,
        }
        self._event_log(
            phase="command",
            event="BRIDGE_COMMAND_END",
            level="ERROR" if ack_value.get("error") else "DEBUG",
            attributes={
                "command": command,
                "request_id": request_id,
                "event_count": len(events),
                "verified": verified,
                "acknowledged": ack is not None and not bool(ack_value.get("error")),
            },
            correlation_refs=(request_id,),
        )
        self._metric(
            name="minecraft.bridge.command_events",
            value=float(len(events)),
            labels={"command": command, "verified": str(verified).lower()},
        )
        if bridge_memory is not None:
            for metric_name, key in (
                ("minecraft.bridge.heap_used_bytes", "heap_used_bytes"),
                ("minecraft.bridge.heap_size_limit_bytes", "heap_size_limit_bytes"),
                ("minecraft.bridge.rss_bytes", "rss_bytes"),
            ):
                value = bridge_memory.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self._metric(
                        name=metric_name,
                        value=float(value),
                        labels={"command": command},
                    )
        return MinecraftBridgeCommandResult(
            command=command,
            acknowledged=ack is not None and not bool(ack_value.get("error")),
            events=tuple(events),
            diagnostics=diagnostics,
        )

    def _start_owned(self) -> None:
        """Start and handshake the bridge on its actor-owned lifecycle lane.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the number of handshake events consumed plus the declared action capabilities inspected; the capability validation pass and event-consumption loop are sequential phases, not a Cartesian product.
        """
        if self._closing:
            raise MinecraftBridgeError("start", "BRIDGE_CLOSING", "bridge close is in progress")
        if self._transport.started:
            raise MinecraftBridgeError("start", "BRIDGE_ALREADY_STARTED", "bridge already started")
        started_at = time.monotonic()
        self._event_log(
            phase="start",
            event="BRIDGE_PROCESS_START",
            attributes={
                "command": self.spec.command,
                "cwd": self.spec.cwd,
                "host": self.endpoint.host,
                "port": self.endpoint.bound_port,
            },
        )
        try:
            self._transport.start()
            # Event sequence numbers are generated by the short-lived Node
            # bridge process, not by the durable Minecraft world/session.  A
            # fresh opaque stream identity fences monotonicity to exactly one
            # transport generation so recycle/restart may legally restart seq.
            self._event_stream_id = uuid4().hex
            request_id = "minecraft-connect"
            self._transport.send(
                "connect",
                {
                    "host": self.endpoint.host,
                    "port": self.endpoint.bound_port,
                    "username": self.agent.username,
                    "auth": self.agent.auth,
                    **({"version": self.agent.version} if self.agent.version else {}),
                    **(
                        {"action_recovery_dir": str(self._action_recovery_dir)}
                        if self._action_recovery_dir is not None
                        else {}
                    ),
                },
                request_id=request_id,
            )
            deadline = time.monotonic() + self.spec.connect_timeout_s
            spawned = False
            while time.monotonic() < deadline:
                message = self._transport.read(timeout_s=max(0.001, deadline - time.monotonic()))
                if message.kind != "event":
                    continue
                event = self._event(message)
                if event.kind == "bridge_status" and event.payload.get("status") == "spawned":
                    observed_version = str(event.payload.get("version") or "")
                    if self.agent.version and observed_version and observed_version != self.agent.version:
                        self._failure_log(
                            phase="handshake",
                            code="MINECRAFT_VERSION_DRIFT",
                            message=f"expected={self.agent.version!r}; observed={observed_version!r}",
                        )
                        raise MinecraftBridgeError(
                            "handshake", "MINECRAFT_VERSION_DRIFT", f"expected={self.agent.version!r}; observed={observed_version!r}"
                        )
                    observed_actions = event.payload.get("action_types")
                    if not isinstance(observed_actions, list) or any(
                        not isinstance(value, str) for value in observed_actions
                    ):
                        raise MinecraftBridgeError(
                            "handshake",
                            "MINECRAFT_CAPABILITY_MANIFEST_MISSING",
                            "bridge did not declare a string action_types manifest",
                        )
                    observed_action_set = frozenset(observed_actions)
                    if (
                        len(observed_action_set) != len(observed_actions)
                        or observed_action_set != MINECRAFT_ACTION_TYPES
                    ):
                        missing = sorted(MINECRAFT_ACTION_TYPES - observed_action_set)
                        extra = sorted(observed_action_set - MINECRAFT_ACTION_TYPES)
                        raise MinecraftBridgeError(
                            "handshake",
                            "MINECRAFT_CAPABILITY_DRIFT",
                            f"missing={missing}; extra={extra}",
                        )
                    raw_settlement_ms = event.payload.get("terminal_settlement_ms")
                    if (
                        isinstance(raw_settlement_ms, bool)
                        or not isinstance(raw_settlement_ms, (int, float))
                        or not math.isfinite(float(raw_settlement_ms))
                        or float(raw_settlement_ms) <= 0
                    ):
                        raise MinecraftBridgeError(
                            "handshake",
                            "MINECRAFT_TERMINAL_SETTLEMENT_CONTRACT_MISSING",
                            "bridge did not declare a positive terminal_settlement_ms",
                        )
                    self._terminal_settlement_timeout_s = float(raw_settlement_ms) / 1000.0
                    spawned = True
                    break
                if event.kind in {"error", "kicked", "end"}:
                    self._failure_log(
                        phase="handshake",
                        code="MINECRAFT_SPAWN_FAILED",
                        message=f"event={event.kind}",
                        attributes={"payload": dict(event.payload)},
                    )
                    raise MinecraftBridgeError(
                        "handshake", "MINECRAFT_SPAWN_FAILED", f"event={event.kind}; payload={dict(event.payload)}"
                    )
            if not spawned:
                self._failure_log(
                    phase="handshake",
                    code="MINECRAFT_SPAWN_TIMEOUT",
                    message="bridge did not emit spawned",
                )
                raise MinecraftBridgeError("handshake", "MINECRAFT_SPAWN_TIMEOUT", "bridge did not emit spawned")
            self._event_log(
                phase="start",
                event="BRIDGE_PROCESS_READY",
                level="INFO",
                attributes={"duration_s": time.monotonic() - started_at, "process_id": self.process_id},
            )
        except Exception:
            self._close_owned()
            raise

    def start(self) -> None:
        self._call_owned("start", self._start_owned)

    def _recycle_transport_owned(self, *, reason: str) -> bool:
        """Recycle only the bridge process after the prior command is durably returned.

        The Java server/world and scientific session identity are preserved. This
        method is called only at a subsequent command/reconciliation boundary, so
        the previous action result has already escaped to the durable effect layer.
        """
        previous_process_id = self.process_id
        if self._transport.started:
            self._close_owned()
        if self._transport.started:
            raise MinecraftBridgeError(
                "restart",
                "BRIDGE_RECYCLE_NOT_CONVERGED",
                f"reason={reason}; previous_process_id={previous_process_id}",
            )
        self._start_owned()
        self._recycle_pending = False
        self._event_log(
            phase="restart",
            event="BRIDGE_PROCESS_RECYCLED",
            level="INFO",
            attributes={
                "reason": reason,
                "previous_process_id": previous_process_id,
                "process_id": self.process_id,
            },
        )
        self._metric(
            name="minecraft.bridge.recycle",
            value=1.0,
            labels={"reason": reason},
        )
        return True

    def _restart_dead_transport_owned(self, *, reason: str) -> bool:
        if not self._transport.started or self._transport.alive:
            return False
        previous_process_id = self.process_id
        cleanup_error: BaseException | None = None
        try:
            self._transport.close()
        except BaseException as exc:
            cleanup_error = exc
            self._failure_log(
                phase="restart",
                code="BRIDGE_DEAD_TRANSPORT_CLEANUP_FAILED",
                message=safe_exception_message(exc),
                exception=exc,
                attributes={"reason": reason, "previous_process_id": previous_process_id},
            )
        if self._transport.started:
            if cleanup_error is not None:
                raise cleanup_error
            raise MinecraftBridgeError(
                "restart",
                "BRIDGE_DEAD_TRANSPORT_NOT_CONVERGED",
                f"reason={reason}; previous_process_id={previous_process_id}",
            )
        try:
            self._start_owned()
        except BaseException as restart_error:
            if cleanup_error is None:
                raise
            raise BaseExceptionGroup(
                "Minecraft bridge dead-transport cleanup and restart both failed",
                [cleanup_error, restart_error],
            ) from restart_error
        self._event_log(
            phase="restart",
            event="BRIDGE_PROCESS_RESTARTED",
            level="INFO",
            attributes={
                "reason": reason,
                "previous_process_id": previous_process_id,
                "process_id": self.process_id,
                "cleanup_error": None if cleanup_error is None else safe_exception_message(cleanup_error),
            },
        )
        return True

    def _defer_observation_events(
        self, events: tuple[MinecraftObservationEvent, ...]
    ) -> None:
        if not events:
            return
        queue = getattr(self, "_deferred_observation_events", None)
        if queue is None:
            queue = deque()
            self._deferred_observation_events = queue
        queue.extend(events)

    def _merge_deferred_observation_events(
        self, events: tuple[MinecraftObservationEvent, ...]
    ) -> tuple[MinecraftObservationEvent, ...]:
        queue = getattr(self, "_deferred_observation_events", None)
        if not queue:
            return events
        prior = tuple(queue)
        queue.clear()
        return prior + events

    def _command_owned(
        self,
        command: str,
        payload: Mapping[str, JsonValue],
        timeout_s: float,
        control: ExecutionControlPort | None = None,
    ) -> MinecraftBridgeCommandResult:
        if self._closing:
            raise MinecraftBridgeError("command", "BRIDGE_CLOSING", "bridge close is in progress")
        if command in MINECRAFT_ACTION_TYPES:
            action_id = payload.get("action_id")
            request_digest = payload.get("_request_digest")
            if not isinstance(action_id, str) or not action_id.strip():
                raise MinecraftBridgeError(
                    "command",
                    "BRIDGE_ACTION_IDENTITY_MISSING",
                    "physical action requires non-empty action_id",
                )
            if (
                not isinstance(request_digest, str)
                or len(request_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in request_digest)
            ):
                raise MinecraftBridgeError(
                    "command",
                    "BRIDGE_ACTION_IDENTITY_MISSING",
                    "physical action requires canonical SHA-256 _request_digest",
                )
            self._bind_request_identity(action_id, request_digest)
            self._bind_action_unit_lineage(
                action_id,
                payload.get("_action_invocation_unit_digest"),
                payload.get("_action_authorization_unit_digest"),
            )
        if self._recycle_pending:
            self._recycle_transport_owned(reason=f"deferred-before-command:{command}")
        else:
            self._restart_dead_transport_owned(reason=f"command:{command}")
        request_id = self._next_request_id(command, payload)
        started_at = time.monotonic()
        self._event_log(
            phase="command",
            event="BRIDGE_COMMAND_START",
            attributes={
                "command": command,
                "request_id": request_id,
                "payload_keys": tuple(sorted(str(key) for key in payload)),
                "payload_digest": hashlib.sha256(
                    json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=repr).encode("utf-8")
                ).hexdigest(),
            },
            correlation_refs=(request_id,),
        )
        try:
            self._transport.send(command, payload, request_id=request_id)
            result = self._observe_until_ack(
                command=command,
                request_id=request_id,
                timeout_s=timeout_s,
                control=control,
            )
        except BaseException as exc:
            # Unknown delivery/terminal status must fence the transport.
            # World and server lifetimes are not owned by this short-lived
            # bridge and are unaffected by the deferred recycle.
            action_id = payload.get("action_id") if command in MINECRAFT_ACTION_TYPES else None
            if isinstance(action_id, str) and action_id:
                self._unacknowledged_actions.add(action_id)
                # Best-effort out-of-band preemption on the *same* provider
                # transport. This never proves that the physical effect was
                # cancelled: the outstanding Unit remains UNKNOWN and the
                # transport must still be fenced before its next command.
                request_digest = payload.get("_request_digest")
                if isinstance(request_digest, str) and request_digest:
                    try:
                        self._transport.send(
                            "interrupt_action",
                            {
                                "action_id": action_id,
                                "request_digest": request_digest,
                                "reason": "UPSTREAM_ACTION_INTERRUPTED",
                            },
                            request_id=f"{request_id}:interrupt",
                        )
                    except Exception:
                        # A broken pipe is precisely why outcome stays unknown.
                        pass
            self._recycle_pending = True
            latency = time.monotonic() - started_at
            cause_code = str(getattr(exc, "cause_code", type(exc).__name__))
            self._event_log(
                phase="command",
                event="BRIDGE_COMMAND_UNACKNOWLEDGED",
                level="ERROR",
                attributes={
                    "command": command,
                    "request_id": request_id,
                    "action_id": action_id,
                    "process_id": self.process_id,
                    "transport_stream_id": self._event_stream_id,
                    "latency_s": latency,
                    "failure_code": cause_code,
                    "effect_disposition": "unknown",
                    "recycle_before_next_command": True,
                },
                correlation_refs=(request_id,),
            )
            self._failure_log(
                phase="command",
                code="BRIDGE_COMMAND_UNACKNOWLEDGED",
                message=f"command={command}; request_id={request_id}; cause={cause_code}",
                exception=exc,
                attributes={"latency_s": latency, "process_id": self.process_id},
                correlation_refs=(request_id,),
            )
            self._metric(
                name="minecraft.bridge.command_latency_s",
                value=latency,
                labels={"command": command, "result": "unacknowledged"},
            )
            raise
        command_latency_s = time.monotonic() - started_at
        merged_events = self._merge_deferred_observation_events(result.events)
        self._metric(
            name="minecraft.bridge.command_latency_s",
            value=command_latency_s,
            labels={"command": command, "result": "error" if result.diagnostics.get("error") else "ok"},
        )
        # Keep the already-measured latency on the returned observation path as
        # well as diagnostics metrics so performance evidence survives even when
        # the configured diagnostics sink is intentionally non-durable.
        return MinecraftBridgeCommandResult(
            result.command,
            result.acknowledged,
            merged_events,
            {
                **dict(result.diagnostics),
                "command_latency_s": command_latency_s,
                "deferred_event_count": len(merged_events) - len(result.events),
            },
        )

    def command(
        self,
        command: str,
        payload: Mapping[str, JsonValue],
        *,
        timeout_s: float,
        control: ExecutionControlPort | None = None,
    ) -> MinecraftBridgeCommandResult:
        if not command.strip():
            raise ValueError("Minecraft bridge command must be non-empty")
        if timeout_s <= 0:
            raise ValueError("Minecraft bridge command timeout must be positive")
        return self._call_owned(
            "command",
            self._command_owned,
            command,
            payload,
            timeout_s,
            control,
        )

    def _bind_request_identity(self, action_id: str, request_digest: str) -> None:
        if not action_id.strip() or not request_digest.strip():
            raise ValueError("Minecraft action ID and digest must be non-empty")
        prior = self._action_request_digests.get(action_id)
        if prior is not None and prior != request_digest:
            raise ActionIdentityViolation(
                "Minecraft action ID reused with a different request digest"
            )
        self._action_request_digests[action_id] = request_digest

    def _bind_action_unit_lineage(
        self, action_id: str, invocation_digest: str, authorization_digest: str
    ) -> None:
        for name, value in (
            ("invocation", invocation_digest),
            ("authorization", authorization_digest),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise MinecraftBridgeError(
                    "command",
                    "BRIDGE_ACTION_UNIT_IDENTITY_MISSING",
                    f"physical action requires canonical {name} Unit digest",
                )
        lineage = (invocation_digest, authorization_digest)
        prior = self._action_unit_lineage.get(action_id)
        if prior is not None and prior != lineage:
            raise ActionIdentityViolation(
                "Minecraft action ID reused with different invocation/authorization Units"
            )
        self._action_unit_lineage[action_id] = lineage

    def _prepare_action_owned(
        self,
        action_id: str,
        request_digest: str,
        action_type: str,
        invocation_unit_digest: str,
        authorization_unit_digest: str,
    ) -> None:
        if not action_id.strip() or not action_type.strip():
            raise ValueError("Minecraft prepared action identity must be non-empty")
        self._bind_request_identity(action_id, request_digest)
        self._bind_action_unit_lineage(
            action_id, invocation_unit_digest, authorization_unit_digest
        )
        if self._recycle_pending:
            self._recycle_transport_owned(reason="deferred-before-prepare")
        else:
            self._restart_dead_transport_owned(reason="prepare_action")
        request_id = (
            "prepare-"
            + hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:16]
            + f"-{self._request_counter + 1}"
        )
        self._request_counter += 1
        self._transport.send(
            "prepare_action",
            {
                "action_id": action_id,
                "request_digest": request_digest,
                "action_type": action_type,
                "_action_invocation_unit_digest": invocation_unit_digest,
                "_action_authorization_unit_digest": authorization_unit_digest,
            },
            request_id=request_id,
        )
        response = self._observe_until_ack(
            command="prepare_action",
            request_id=request_id,
            timeout_s=self.spec.command_timeout_s,
        )
        self._defer_observation_events(response.events)
        ack = response.diagnostics.get("ack")
        if not isinstance(ack, Mapping):
            raise MinecraftBridgeError(
                "prepare", "BRIDGE_INVALID_ACTION_PREPARE", "prepare_action omitted ack"
            )
        state = str(ack.get("state") or "")
        disposition = str(ack.get("disposition") or "")
        durability = str(ack.get("durability") or "")
        if state not in {"prepared", "intent", "terminal"}:
            raise MinecraftBridgeError(
                "prepare", "BRIDGE_INVALID_ACTION_PREPARE", f"state={state!r}"
            )
        if disposition not in {"not_applied", "unknown", "applied", "rejected"}:
            raise MinecraftBridgeError(
                "prepare",
                "BRIDGE_INVALID_ACTION_PREPARE",
                f"disposition={disposition!r}",
            )
        if self._action_recovery_dir is not None and durability != "crash_durable":
            raise MinecraftBridgeError(
                "prepare",
                "BRIDGE_ACTION_PREPARE_NOT_DURABLE",
                f"durability={durability!r}",
            )

    def prepare_action(
        self,
        action_id: str,
        *,
        request_digest: str,
        action_type: str,
        invocation_unit_digest: str,
        authorization_unit_digest: str,
    ) -> None:
        self._call_owned(
            "prepare-action",
            self._prepare_action_owned,
            action_id,
            request_digest,
            action_type,
            invocation_unit_digest,
            authorization_unit_digest,
        )

    def _reconcile_action_owned(
        self,
        action_id: str,
        request_digest: str,
        invocation_unit_digest: str | None = None,
        authorization_unit_digest: str | None = None,
    ) -> MinecraftReconciliation:
        previously_bound = self._action_request_digests.get(action_id)
        self._bind_request_identity(action_id, request_digest)
        if (invocation_unit_digest is None) != (authorization_unit_digest is None):
            raise MinecraftBridgeError(
                "reconcile",
                "BRIDGE_ACTION_UNIT_IDENTITY_MISSING",
                "reconciliation requires both invocation and authorization Unit digests",
            )
        if invocation_unit_digest is not None and authorization_unit_digest is not None:
            self._bind_action_unit_lineage(
                action_id, invocation_unit_digest, authorization_unit_digest
            )
        lineage = self._action_unit_lineage.get(action_id)
        if lineage is None:
            raise MinecraftBridgeError(
                "reconcile",
                "BRIDGE_ACTION_UNIT_IDENTITY_MISSING",
                "reconciliation has no bound invocation/authorization Unit identity",
            )
        local = self._action_proofs.get(action_id)
        if (
            action_id in self._unacknowledged_actions
            and self.action_recovery_durability != "crash_durable"
            and local not in {
                ActionReconciliationDisposition.APPLIED,
                ActionReconciliationDisposition.REJECTED,
                ActionReconciliationDisposition.NOT_APPLIED,
            }
        ):
            # A recycled process-local action journal cannot prove that an
            # earlier physical effect never occurred. Do not allow the newly
            # spawned empty journal to produce a false NOT_APPLIED result.
            return MinecraftReconciliation(
                action_id=action_id,
                disposition=ActionReconciliationDisposition.UNKNOWN,
                diagnostics={
                    "proof_source": "lost_process_local_action_journal",
                    "durability": self.action_recovery_durability,
                    "bridge_restarted": False,
                },
            )
        # UNKNOWN is absence of a terminal proof, not a permanent verdict.
        # A later read of the durable provider WAL may resolve a lost ACK.
        # Short-circuiting a cached UNKNOWN would prevent reconciliation.
        if (
            previously_bound == request_digest
            and self._action_proof_digests.get(action_id) == request_digest
            and local in {
                ActionReconciliationDisposition.APPLIED,
                ActionReconciliationDisposition.REJECTED,
                ActionReconciliationDisposition.NOT_APPLIED,
            }
        ):
            return MinecraftReconciliation(
                action_id=action_id,
                disposition=local,
                diagnostics={
                    "proof_source": "action_result_event",
                    "known_action_proof": local.value,
                    "durability": self.action_recovery_durability,
                },
            )
        bridge_restarted = (
            self._recycle_transport_owned(reason="deferred-before-reconcile")
            if self._recycle_pending
            else self._restart_dead_transport_owned(reason="reconcile_action")
        )
        request_id = f"reconcile-{hashlib.sha256(action_id.encode('utf-8')).hexdigest()[:16]}-{self._request_counter + 1}"
        self._request_counter += 1
        self._transport.send(
            "reconcile_action",
            {
                "action_id": action_id,
                "request_digest": request_digest,
                "_action_invocation_unit_digest": lineage[0],
                "_action_authorization_unit_digest": lineage[1],
            },
            request_id=request_id,
        )
        response = self._observe_until_ack(
            command="reconcile_action",
            request_id=request_id,
            timeout_s=self.spec.command_timeout_s,
        )
        self._defer_observation_events(response.events)
        ack = response.diagnostics.get("ack")
        raw = ack.get("disposition") if isinstance(ack, Mapping) else None
        raw_outcome = ack.get("outcome") if isinstance(ack, Mapping) else None
        if raw_outcome is not None and not isinstance(raw_outcome, Mapping):
            raise MinecraftBridgeError(
                "reconcile",
                "BRIDGE_INVALID_RECONCILIATION",
                "provider outcome must be a mapping when present",
            )
        provider_outcome = dict(raw_outcome) if isinstance(raw_outcome, Mapping) else None
        try:
            disposition = ActionReconciliationDisposition(str(raw))
        except ValueError as exc:
            raise MinecraftBridgeError(
                "reconcile", "BRIDGE_INVALID_RECONCILIATION", f"disposition={raw!r}"
            ) from exc
        self._record_action_proof(
            action_id,
            disposition,
            source=(
                "durable_action_journal"
                if self._action_recovery_dir is not None
                else "process_action_journal"
            ),
            request_digest=request_digest,
        )
        return MinecraftReconciliation(
            action_id=action_id,
            disposition=disposition,
            diagnostics={
                "proof_source": "durable_action_journal"
                if self._action_recovery_dir is not None
                else "process_action_journal",
                "known_action_proof": disposition.value,
                "durability": self.action_recovery_durability,
                "provider_outcome": provider_outcome,
                "bridge_restarted": bridge_restarted,
            },
        )

    def reconcile_action(
        self,
        action_id: str,
        *,
        request: ActionRequest,
        context: ExecutionContext,
        request_digest: str | None = None,
        invocation_unit_digest: str,
        authorization_unit_digest: str,
    ) -> MinecraftReconciliation:
        del context
        if not action_id.strip():
            raise ValueError("Minecraft action_id must be non-empty")
        digest = request_digest or action_request_digest(request)
        return self._call_owned(
            "reconcile-action",
            self._reconcile_action_owned,
            action_id,
            digest,
            invocation_unit_digest,
            authorization_unit_digest,
        )

    def _close_owned(self) -> None:
        if not self._transport.started or self._closing:
            return
        self._closing = True
        self._event_log(
            phase="close",
            event="BRIDGE_PROCESS_CLOSE",
            attributes={"process_id": self.process_id},
            level="INFO",
        )
        try:
            try:
                self._transport.send("quit", {}, request_id="minecraft-close")
            except MinecraftBridgeError:
                pass
            self._transport.close()
        finally:
            # Only a successfully restarted process with an established
            # handshake may clear the pending recycle fence.
            self._closing = False
        self._event_stream_id = None

    def close(self) -> None:
        self._call_owned("close", self._close_owned)




__all__ = ["JsonlMinecraftBridge", "JsonlProcess", "MinecraftBridgeError"]
