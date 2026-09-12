from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tests._concurrency_support import make_task_group
from noetrium_platform.capabilities.environment.minecraft.api import MinecraftBridgeSpec
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_transport import (
    JsonlProcessTransport,
    MinecraftBridgeError,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute


class _ExitedProcess:
    def __init__(self, stdout: str, stderr: str = "") -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.pid = 4242

    def poll(self) -> int | None:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def terminate(self) -> None:
        raise AssertionError("exited process must not be terminated")

    def kill(self) -> None:
        raise AssertionError("exited process must not be killed")


def _transport(process: _ExitedProcess) -> JsonlProcessTransport:
    return JsonlProcessTransport(
        spec=MinecraftBridgeSpec(
            command=("fake-node",),
            cwd=".",
            command_timeout_s=1,
            connect_timeout_s=1,
        ),
        operating_system=LocalOperatingSystemRoute(),
        task_group=make_task_group("minecraft-jsonl-transport"),
        bridge_identity="transport-test",
        process_factory=lambda _command, **_kwargs: process,
    )


def test_transport_owns_jsonl_framing_and_stderr_capture() -> None:
    process = _ExitedProcess(
        json.dumps({"type": "ack", "cmd": "ping", "request_id": "req-1"}) + "\n",
        "provider-warning\n",
    )
    transport = _transport(process)
    transport.start()
    transport.send("ping", {"value": 1}, request_id="req-1")
    message = transport.read(timeout_s=1)
    transport.close()

    assert message.kind == "ack"
    assert message.value["request_id"] == "req-1"
    sent = json.loads(process.stdin.getvalue().strip())
    assert sent == {"cmd": "ping", "request_id": "req-1", "value": 1}
    assert transport.stderr_tail == ("provider-warning",)
    assert transport.stderr_tail_text() == "provider-warning"
    assert transport.process_id is None


def test_transport_rejects_invalid_json_with_stable_cause_code() -> None:
    transport = _transport(_ExitedProcess("not-json\n"))
    transport.start()

    with pytest.raises(MinecraftBridgeError) as raised:
        transport.read(timeout_s=1)

    assert raised.value.phase == "decode"
    assert raised.value.cause_code == "BRIDGE_INVALID_JSON"
    transport.close()


def test_transport_rejects_send_before_start() -> None:
    transport = _transport(_ExitedProcess(""))
    with pytest.raises(MinecraftBridgeError, match="BRIDGE_NOT_STARTED"):
        transport.send("ping", {}, request_id="req-1")


def test_transport_adds_bridge_node_modules_to_child_environment(
    tmp_path: Path, monkeypatch
) -> None:
    bridge_root = tmp_path / "bridge"
    (bridge_root / "node_modules").mkdir(parents=True)
    monkeypatch.setenv("MC_BRIDGE_DIR", str(bridge_root))
    monkeypatch.delenv("NODE_PATH", raising=False)
    process = _ExitedProcess("")
    captured: dict[str, object] = {}

    def factory(_command, **kwargs):
        captured.update(kwargs)
        return process

    transport = JsonlProcessTransport(
        spec=MinecraftBridgeSpec(
            command=("fake-node",), cwd=".", command_timeout_s=1, connect_timeout_s=1
        ),
        operating_system=LocalOperatingSystemRoute(),
        task_group=make_task_group("minecraft-jsonl-node-path"),
        bridge_identity="node-path-test",
        process_factory=factory,
    )
    transport.start()
    try:
        environment = captured["env"]
        assert isinstance(environment, dict)
        assert environment["NODE_PATH"] == str(bridge_root / "node_modules")
    finally:
        transport.close()
