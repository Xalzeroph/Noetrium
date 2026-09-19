from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
import time
from typing import Mapping
from uuid import uuid4

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionReconciliationDisposition,
    ActionRequest,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import SerialActorPort, TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue
from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute

from ..api import (
    MINECRAFT_ACTION_TYPES,
    MinecraftBridgeCommandResult,
    MinecraftBridgeEnvelope,
    MinecraftBridgePort,
    MinecraftBridgeSpec,
    MinecraftActionOutcomeStatus,
    MinecraftActionResultEvidence,
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
    ProcessTerminator,
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
        process_terminator: ProcessTerminator | None = None,
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
        actor_identity = hashlib.sha256(
            f"{endpoint.host}:{endpoint.port}:{agent.username}".encode("utf-8")
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
            process_terminator=process_terminator,
            failure_reporter=self._failure_log,
            stderr_tail_lines=stderr_tail_lines,
        )
        self._actor: SerialActorPort = task_group.open_serial_actor(
            f"minecraft-bridge:{actor_identity}:{uuid4().hex}",
            lane_id=f"minecraft-bridge:{actor_identity}",
        )
        self._closing = False

    @property
    def action_recovery_durability(self) -> str:
        return "crash_durable" if self._action_recovery_root is not None else "process_local"

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
            "quit",
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

    @staticmethod
    def _event(message: JsonlBridgeMessage) -> MinecraftObservationEvent:
        if message.kind != "event":
            raise MinecraftBridgeError("decode", "BRIDGE_UNEXPECTED_MESSAGE", message.kind)
        try:
            return MinecraftBridgeEnvelope.from_mapping(message.value).as_observation()
        except (TypeError, ValueError) as exc:
            raise MinecraftBridgeError("decode", "BRIDGE_INVALID_EVENT", safe_exception_message(exc)) from exc

    def _observe_until_ack(
        self,
        *,
        command: str,
        request_id: str,
        timeout_s: float,
        require_ack: bool = True,
    ) -> MinecraftBridgeCommandResult:
        deadline = time.monotonic() + timeout_s
        events: list[MinecraftObservationEvent] = []
        ack: Mapping[str, JsonValue] | None = None
        while time.monotonic() < deadline:
            message = self._transport.read(timeout_s=max(0.001, deadline - time.monotonic()))
            if message.kind == "event":
                event = self._event(message)
                events.append(event)
                if event.kind == "action_result":
                    try:
                        evidence = MinecraftActionResultEvidence.from_event(
                            event,
                            expected_action_id=request_id,
                            expected_action_type=command,
                        )
                    except (TypeError, ValueError) as exc:
                        raise MinecraftBridgeError(
                            "decode",
                            "BRIDGE_INVALID_ACTION_RESULT",
                            safe_exception_message(exc),
                        ) from exc
                    disposition = {
                        MinecraftActionOutcomeStatus.APPLIED: ActionReconciliationDisposition.APPLIED,
                        MinecraftActionOutcomeStatus.REJECTED: ActionReconciliationDisposition.NOT_APPLIED,
                        MinecraftActionOutcomeStatus.PARTIAL: ActionReconciliationDisposition.UNKNOWN,
                    }[evidence.status]
                    self._action_proofs[evidence.action_id] = disposition
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
        diagnostics = {
            "request_id": request_id,
            "event_count": len(events),
            "ack": ack_value,
            "stderr_tail": self.stderr_tail,
            "process_id": self.process_id,
            "error": ack_value.get("error"),
            "diagnostic_errors": tuple(self._diagnostic_errors),
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
        return MinecraftBridgeCommandResult(
            command=command,
            acknowledged=ack is not None and not bool(ack_value.get("error")),
            verified=verified,
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
                "port": self.endpoint.port,
            },
        )
        try:
            self._transport.start()
            request_id = "minecraft-connect"
            self._transport.send(
                "connect",
                {
                    "host": self.endpoint.host,
                    "port": self.endpoint.port,
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
        self._actor.call("start", self._start_owned)

    def _command_owned(
        self,
        command: str,
        payload: Mapping[str, JsonValue],
        timeout_s: float,
    ) -> MinecraftBridgeCommandResult:
        if self._closing:
            raise MinecraftBridgeError("command", "BRIDGE_CLOSING", "bridge close is in progress")
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
        self._transport.send(command, payload, request_id=request_id)
        result = self._observe_until_ack(
            command=command,
            request_id=request_id,
            timeout_s=timeout_s,
        )
        self._metric(
            name="minecraft.bridge.command_latency_s",
            value=time.monotonic() - started_at,
            labels={"command": command, "result": "error" if result.diagnostics.get("error") else "ok"},
        )
        return result

    def command(
        self,
        command: str,
        payload: Mapping[str, JsonValue],
        *,
        timeout_s: float,
    ) -> MinecraftBridgeCommandResult:
        if not command.strip():
            raise ValueError("Minecraft bridge command must be non-empty")
        if timeout_s <= 0:
            raise ValueError("Minecraft bridge command timeout must be positive")
        return self._actor.call("command", self._command_owned, command, payload, timeout_s)

    def _reconcile_action_owned(
        self, action_id: str, request_digest: str
    ) -> MinecraftReconciliation:
        local = self._action_proofs.get(action_id)
        if local in {
            ActionReconciliationDisposition.APPLIED,
            ActionReconciliationDisposition.NOT_APPLIED,
        }:
            return MinecraftReconciliation(
                action_id=action_id,
                disposition=local,
                diagnostics={
                    "proof_source": "action_result_event",
                    "known_action_proof": local.value,
                    "durability": self.action_recovery_durability,
                },
            )
        request_id = f"reconcile-{hashlib.sha256(action_id.encode('utf-8')).hexdigest()[:16]}-{self._request_counter + 1}"
        self._request_counter += 1
        self._transport.send(
            "reconcile_action",
            {"action_id": action_id, "request_digest": request_digest},
            request_id=request_id,
        )
        response = self._observe_until_ack(
            command="reconcile_action",
            request_id=request_id,
            timeout_s=self.spec.command_timeout_s,
        )
        ack = response.diagnostics.get("ack")
        raw = ack.get("disposition") if isinstance(ack, Mapping) else None
        try:
            disposition = ActionReconciliationDisposition(str(raw))
        except ValueError as exc:
            raise MinecraftBridgeError(
                "reconcile", "BRIDGE_INVALID_RECONCILIATION", f"disposition={raw!r}"
            ) from exc
        if disposition is not ActionReconciliationDisposition.UNKNOWN:
            self._action_proofs[action_id] = disposition
        return MinecraftReconciliation(
            action_id=action_id,
            disposition=disposition,
            diagnostics={
                "proof_source": "durable_action_journal"
                if self._action_recovery_dir is not None
                else "process_action_journal",
                "known_action_proof": disposition.value,
                "durability": self.action_recovery_durability,
            },
        )

    def reconcile_action(
        self,
        action_id: str,
        *,
        request: ActionRequest,
        context: ExecutionContext,
        request_digest: str | None = None,
    ) -> MinecraftReconciliation:
        del context
        if not action_id.strip():
            raise ValueError("Minecraft action_id must be non-empty")
        digest = request_digest or action_request_digest(request)
        return self._actor.call(
            "reconcile-action", self._reconcile_action_owned, action_id, digest
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
            self._closing = False

    def close(self) -> None:
        self._actor.call("close", self._close_owned)




__all__ = ["JsonlMinecraftBridge", "JsonlProcess", "MinecraftBridgeError", "ProcessTerminator"]
