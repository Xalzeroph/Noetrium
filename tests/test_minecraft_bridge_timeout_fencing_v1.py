"""Regressions for a provider lane whose terminal ACK was never observed."""

from collections import deque
from types import SimpleNamespace
import hashlib

import pytest

from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import (
    JsonlMinecraftBridge,
    MinecraftBridgeError,
)


def _unit_lineage(action_id: str, request_digest: str) -> tuple[str, str]:
    invocation = hashlib.sha256(
        f"invocation:{action_id}:{request_digest}".encode("utf-8")
    ).hexdigest()
    authorization = hashlib.sha256(
        f"authorization:{action_id}:{request_digest}".encode("utf-8")
    ).hexdigest()
    return invocation, authorization


def _wire_action(action_id: str, request_digest: str, **payload):
    invocation, authorization = _unit_lineage(action_id, request_digest)
    return {
        "action_id": action_id,
        "_request_digest": request_digest,
        "_action_invocation_unit_digest": invocation,
        "_action_authorization_unit_digest": authorization,
        **payload,
    }


class UnacknowledgedBridgeTransport:
    def __init__(self):
        self.sent = []
        self.recycled = False
        self.process_id = 123
        self.stderr_tail = ()

    def send(self, command, payload, *, request_id):
        if self.sent and not self.recycled:
            raise AssertionError("sent a second physical effect before fencing stale bridge")
        self.sent.append((command, request_id))

    def read(self, *, timeout_s, control=None):
        if not self.recycled:
            raise MinecraftBridgeError(
                "read", "BRIDGE_READ_TIMEOUT", "no correlated terminal ACK"
            )
        return SimpleNamespace(
            kind="ack",
            value={"cmd": self.sent[-1][0], "request_id": self.sent[-1][1]},
        )


def test_unacknowledged_action_fences_process_before_next_effect(monkeypatch):
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._closing = False
    bridge._recycle_pending = False
    bridge._request_counter = 0
    bridge._diagnostics = None
    bridge._diagnostic_errors = deque()
    bridge._event_stream_id = "known-bridge-process-stream"
    bridge._unacknowledged_actions = set()
    bridge._action_proofs = {}
    bridge._action_proof_digests = {}
    bridge._action_request_digests = {}
    bridge._action_unit_lineage = {}
    bridge._action_recovery_root = None
    bridge._transport = UnacknowledgedBridgeTransport()
    events = []
    diagnostic_events = []
    diagnostic_metrics = []
    diagnostic_failures = []
    bridge._diagnostics = SimpleNamespace(
        event=lambda **kw: diagnostic_events.append(kw),
        metric=lambda **kw: diagnostic_metrics.append(kw),
        failure=lambda **kw: diagnostic_failures.append(kw),
    )

    monkeypatch.setattr(
        bridge, "_restart_dead_transport_owned",
        lambda **kwargs: events.append("check-dead"),
    )

    def recycle(*, reason):
        assert bridge._recycle_pending is True
        assert len(bridge._transport.sent) == 1
        events.append("recycle")
        bridge._transport.recycled = True
        bridge._recycle_pending = False
        return True

    monkeypatch.setattr(bridge, "_recycle_transport_owned", recycle)

    with pytest.raises(MinecraftBridgeError, match="BRIDGE_READ_TIMEOUT"):
        bridge._command_owned(
            "wait", _wire_action("first", "a" * 64), timeout_s=0.5
        )

    assert bridge._recycle_pending is True
    assert bridge._transport.sent == [("wait", "first")]
    assert "recycle" not in events
    assert "first" in bridge._unacknowledged_actions
    missed = [row for row in diagnostic_events if row["event"] == "BRIDGE_COMMAND_UNACKNOWLEDGED"]
    assert len(missed) == 1
    assert missed[0]["attributes"]["request_id"] == "first"
    assert missed[0]["attributes"]["effect_disposition"] == "unknown"
    assert missed[0]["attributes"]["transport_stream_id"] == "known-bridge-process-stream"
    assert missed[0]["attributes"]["latency_s"] >= 0
    assert any(row["code"] == "BRIDGE_COMMAND_UNACKNOWLEDGED" for row in diagnostic_failures)
    assert any(row["labels"]["result"] == "unacknowledged" for row in diagnostic_metrics)

    uncertain = bridge._reconcile_action_owned("first", "a" * 64)
    assert uncertain.disposition.value == "unknown"
    assert uncertain.diagnostics["proof_source"] == "lost_process_local_action_journal"
    assert "recycle" not in events

    result = bridge._command_owned(
        "wait", _wire_action("second", "b" * 64), timeout_s=0.5
    )
    assert result.acknowledged is True
    assert bridge._recycle_pending is False
    assert bridge._transport.sent == [("wait", "first"), ("wait", "second")]
    assert "recycle" in events


@pytest.mark.parametrize("terminal_kind", ("error", "kicked", "end"))
def test_terminal_minecraft_connection_event_fails_command_immediately(terminal_kind):
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._closing = False
    bridge._recycle_pending = False
    bridge._diagnostics = None
    bridge._diagnostic_errors = deque()
    bridge._event_stream_id = "terminal-stream"
    reads = 0

    def read(**kwargs):
        nonlocal reads
        del kwargs
        reads += 1
        if reads > 1:
            raise AssertionError("waited after authoritative terminal connection event")
        payload = {
            "error": {"message": "protocol decode failed"},
            "kicked": {"reason": "connection lost", "logged_in": True},
            "end": {"reason": "socketClosed"},
        }[terminal_kind]
        return SimpleNamespace(
            kind="event",
            value={
                "type": "event",
                "kind": terminal_kind,
                "seq": 1,
                "ts_ms": 1,
                "request_id": "current-request",
                "payload": payload,
            },
        )

    bridge._transport = SimpleNamespace(
        process_id=321,
        stderr_tail=(),
        stderr_tail_text=lambda: "",
        read=read,
    )
    failures = []
    bridge._diagnostics = SimpleNamespace(
        failure=lambda **kwargs: failures.append(kwargs),
        event=lambda **kwargs: None,
        metric=lambda **kwargs: None,
    )

    with pytest.raises(MinecraftBridgeError, match="MINECRAFT_CONNECTION_TERMINATED"):
        bridge._observe_until_ack(
            command="collect_block",
            request_id="current-request",
            timeout_s=180.0,
        )
    assert reads == 1
    assert bridge._recycle_pending is True
    assert any(row["code"] == "MINECRAFT_CONNECTION_TERMINATED" for row in failures)


def test_uncorrelated_terminal_ack_fences_provider_lane(monkeypatch):
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._closing = False
    bridge._recycle_pending = False
    bridge._diagnostics = None
    bridge._diagnostic_errors = deque()
    bridge._event_stream_id = "known-bridge-process-stream"
    bridge._unacknowledged_actions = set()
    bridge._action_proofs = {}
    bridge._action_proof_digests = {}
    bridge._action_request_digests = {}
    bridge._action_unit_lineage = {}
    bridge._action_recovery_root = None
    bridge._transport = SimpleNamespace(
        process_id=123, stderr_tail=(), stderr_tail_text=lambda: "",
        read=lambda **kwargs: SimpleNamespace(
            kind="ack",
            value={"cmd": "wait", "request_id": "old-request"},
        ),
    )
    monkeypatch.setattr(bridge, "_metric", lambda **kwargs: None)

    # A stream with no correlated ACK cannot establish effect certainty.
    with pytest.raises(MinecraftBridgeError, match="BRIDGE_COMMAND_TIMEOUT"):
        bridge._observe_until_ack(
            command="wait", request_id="current-request", timeout_s=0.003
        )
    assert bridge._recycle_pending is True


@pytest.mark.parametrize(
    ("first_action_mode", "expected_error"),
    (("silent", "BRIDGE_READ_TIMEOUT"), ("eof", "BRIDGE_STDOUT_EOF")),
)
def test_live_transport_timeout_recycles_only_mineflayer_and_preserves_uncertainty(
    first_action_mode, expected_error
):
    """End-to-end transport: both lost ACK and crashed Node fail closed."""
    from tests._concurrency_support import make_task_group
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MinecraftAgentSpec, MinecraftBridgeSpec, MinecraftEndpointSpec,
        MINECRAFT_ACTION_TYPES,
    )
    from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
    import json
    import queue

    class Reader:
        def __init__(self):
            self.queue = queue.Queue()

        def put(self, text):
            self.queue.put(text)

        def readline(self):
            return self.queue.get()

        def close(self):
            self.put("")

    class FakeProcess:
        serial = 11000

        def __init__(self, silent=False, crash=False):
            FakeProcess.serial += 1
            self.pid = FakeProcess.serial
            self.stdout = Reader()
            self.stderr = Reader()
            self.stdin = self
            self.silent = silent
            self.crash = crash
            self.returncode = None

        def write(self, line):
            message = json.loads(line)
            command = str(message["cmd"])
            request_id = message.get("request_id")
            def send(row):
                self.stdout.put(json.dumps(row) + "\n")
            if command == "connect":
                send({
                    "type": "event", "kind": "bridge_status", "seq": 1,
                    "ts_ms": 1, "request_id": request_id,
                    "payload": {
                        "status": "spawned", "version": "1.21.6",
                        "action_types": sorted(MINECRAFT_ACTION_TYPES),
                        "terminal_settlement_ms": 6000,
                    },
                })
            elif command == "wait" and self.silent:
                return len(line)
            elif command == "wait" and self.crash:
                self.returncode = 1
                self.stdout.close()
                self.stderr.close()
                return len(line)
            elif command == "wait":
                send({
                    "type": "event", "kind": "action_result", "seq": 2,
                    "ts_ms": 2, "request_id": request_id,
                    "payload": {
                        "action_id": message["action_id"],
                        "request_digest": message["_request_digest"],
                        "action_invocation_unit_digest": message["_action_invocation_unit_digest"],
                        "action_authorization_unit_digest": message["_action_authorization_unit_digest"],
                        "verified": True,
                        "effect_disposition": "applied",
                        "action": {"tool": "wait"},
                        "outcome": {"status": "applied", "code": "WAIT_COMPLETED"},
                    },
                })
            if command in ("connect", "wait", "quit"):
                send({"type": "ack", "cmd": command, "request_id": request_id})
            if command == "quit":
                self.terminate()
            return len(line)

        def flush(self):
            pass

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return 0 if self.returncode is None else self.returncode

        def terminate(self):
            self.returncode = 0
            self.stdout.close()
            self.stderr.close()

        def kill(self):
            self.terminate()
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
        build_process_supervisor,
    )

    processes = []
    group = make_task_group("minecraft-bridge-missing-ack-regression")

    def factory(*args, **kwargs):
        process = FakeProcess(
            silent=(len(processes) == 0 and first_action_mode == "silent"),
            crash=(len(processes) == 0 and first_action_mode == "eof"),
        )
        processes.append(process)
        return process

    bridge = JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25567),
        spec=MinecraftBridgeSpec(
            command=("fake-node",), cwd=".", command_timeout_s=0.1,
            connect_timeout_s=1,
        ),
        agent=MinecraftAgentSpec(version="1.21.6"),
        operating_system=LocalOperatingSystemRoute(),
        process_factory=factory,
        process_supervisor=build_process_supervisor(group),
        task_group=group,
    )
    try:
        bridge.start()
        assert bridge.terminal_settlement_timeout_s == 6.0
        with pytest.raises(MinecraftBridgeError, match=expected_error):
            bridge.command(
                "wait", _wire_action("uncertain", "0" * 64, ms=1), timeout_s=0.02
            )
        assert len(processes) == 1
        assert bridge._recycle_pending is True

        proof = bridge._reconcile_action_owned("uncertain", "0" * 64)
        assert proof.disposition.value == "unknown"
        assert len(processes) == 1  # Not falsely reconciled by empty journal.

        result = bridge.command(
            "wait", _wire_action("fresh", "f" * 64, ms=1), timeout_s=1
        )
        assert result.acknowledged is True
        assert len(processes) == 2
        assert processes[0].poll() is not None
        assert bridge._recycle_pending is False
    finally:
        bridge.close()
        group.close()



def test_cached_unknown_reprobes_durable_provider_journal(monkeypatch, tmp_path):
    """UNKNOWN is never a terminal proof; a later committed ACK can resolve it."""
    from noetrium_platform.capabilities.environment.api import ActionReconciliationDisposition
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._action_proofs = {"lost-ack": ActionReconciliationDisposition.UNKNOWN}
    bridge._action_proof_digests = {"lost-ack": "a" * 64}
    bridge._action_request_digests = {"lost-ack": "a" * 64}
    bridge._action_unit_lineage = {"lost-ack": _unit_lineage("lost-ack", "a" * 64)}
    bridge._unacknowledged_actions = {"lost-ack"}
    bridge._action_recovery_root = tmp_path
    bridge._action_recovery_dir = tmp_path / "journal"
    bridge._recycle_pending = False
    bridge._request_counter = 0
    bridge._transport = SimpleNamespace(send=lambda *a, **kw: None)
    bridge.spec = SimpleNamespace(command_timeout_s=1)
    monkeypatch.setattr(bridge, "_restart_dead_transport_owned", lambda **kw: False)
    observed = []

    def answer(*, command, request_id, timeout_s):
        observed.append((command, request_id))
        return SimpleNamespace(events=(), diagnostics={
            "ack": {
                "disposition": "applied",
                "outcome": {"status": "applied"},
            }
        })

    monkeypatch.setattr(bridge, "_observe_until_ack", answer)
    resolved = bridge._reconcile_action_owned("lost-ack", "a" * 64)
    assert resolved.disposition is ActionReconciliationDisposition.APPLIED
    assert len(observed) == 1
    assert bridge._action_proofs["lost-ack"] is ActionReconciliationDisposition.APPLIED

    # Terminal proof is now cached, and must not submit another query or effect.
    cached = bridge._reconcile_action_owned("lost-ack", "a" * 64)
    assert cached.disposition is ActionReconciliationDisposition.APPLIED
    assert len(observed) == 1


def test_cached_unknown_without_durable_journal_remains_unknown():
    """A recycled process-local ledger cannot authorize a NOT_APPLIED claim."""
    from noetrium_platform.capabilities.environment.api import ActionReconciliationDisposition
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._action_proofs = {"lost-ack": ActionReconciliationDisposition.UNKNOWN}
    bridge._action_proof_digests = {"lost-ack": "a" * 64}
    bridge._action_request_digests = {"lost-ack": "a" * 64}
    bridge._action_unit_lineage = {"lost-ack": _unit_lineage("lost-ack", "a" * 64)}
    bridge._unacknowledged_actions = {"lost-ack"}
    bridge._action_recovery_root = None
    resolved = bridge._reconcile_action_owned("lost-ack", "a" * 64)
    assert resolved.disposition is ActionReconciliationDisposition.UNKNOWN
    assert resolved.diagnostics["proof_source"] == "lost_process_local_action_journal"



def test_cached_terminal_action_identity_mismatch_is_rejected_before_effect() -> None:
    from noetrium_platform.capabilities.environment.api import (
        ActionIdentityViolation, ActionReconciliationDisposition,
    )
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._action_proofs = {"shared-id": ActionReconciliationDisposition.APPLIED}
    bridge._action_proof_digests = {"shared-id": "a" * 64}
    bridge._action_request_digests = {"shared-id": "a" * 64}
    bridge._action_unit_lineage = {"shared-id": _unit_lineage("shared-id", "a" * 64)}
    with pytest.raises(ActionIdentityViolation, match="different request digest"):
        bridge._reconcile_action_owned("shared-id", "b" * 64)
    assert bridge._action_request_digests["shared-id"] == "a" * 64


def test_unbound_terminal_cache_cannot_shortcut_provider_identity_check(monkeypatch) -> None:
    from noetrium_platform.capabilities.environment.api import ActionReconciliationDisposition
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._action_proofs = {"late-id": ActionReconciliationDisposition.APPLIED}
    bridge._action_proof_digests = {}
    bridge._action_request_digests = {}
    bridge._action_unit_lineage = {}
    bridge._unacknowledged_actions = set()
    bridge._action_recovery_root = None
    bridge._action_recovery_dir = None
    bridge._recycle_pending = False
    bridge._request_counter = 0
    bridge._transport = SimpleNamespace(send=lambda *args, **kwargs: None)
    bridge.spec = SimpleNamespace(command_timeout_s=1)
    monkeypatch.setattr(bridge, "_restart_dead_transport_owned", lambda **kwargs: False)
    queries = []

    def durable_reconcile(*, command, request_id, timeout_s):
        queries.append((command, request_id))
        return SimpleNamespace(events=(), diagnostics={
            "ack": {"disposition": "rejected", "outcome": {"status": "rejected"}}
        })

    monkeypatch.setattr(bridge, "_observe_until_ack", durable_reconcile)
    invocation, authorization = _unit_lineage("late-id", "b" * 64)
    observed = bridge._reconcile_action_owned(
        "late-id", "b" * 64, invocation, authorization
    )
    assert observed.disposition is ActionReconciliationDisposition.REJECTED
    assert len(queries) == 1


def test_prepared_action_cannot_rebind_same_id_to_different_digest() -> None:
    from noetrium_platform.capabilities.environment.api import ActionIdentityViolation
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._action_request_digests = {}
    bridge._action_unit_lineage = {}
    bridge._bind_request_identity("same-id", "a" * 64)
    with pytest.raises(ActionIdentityViolation, match="different request digest"):
        bridge._bind_request_identity("same-id", "b" * 64)
    assert bridge._action_request_digests == {"same-id": "a" * 64}
