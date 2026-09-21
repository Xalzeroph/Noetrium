from __future__ import annotations

import io
import json

import pytest

from noetrium_platform.capabilities.environment.providers import (
    JsonlProcessError,
    JsonlProcessSpec,
    JsonlProcessTransport,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from tests._concurrency_support import make_task_group


class _ExitedProcess:
    def __init__(self, stdout: str, stderr: str = "") -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.pid = 911

    def poll(self):
        return 0

    def wait(self, timeout=None):
        del timeout
        return 0

    def terminate(self):
        raise AssertionError("already exited")

    def kill(self):
        raise AssertionError("already exited")


def _transport(process: _ExitedProcess, **kwargs) -> JsonlProcessTransport:
    return JsonlProcessTransport(
        spec=JsonlProcessSpec(("worker",), "."),
        operating_system=LocalOperatingSystemRoute(),
        task_group=make_task_group("environment-jsonl-generic"),
        transport_identity="generic-test",
        process_factory=lambda _command, **_options: process,
        **kwargs,
    )


def test_generic_transport_frames_requests_and_reads_messages() -> None:
    process = _ExitedProcess(json.dumps({"type": "ready", "request_id": "r1"}) + "\n")
    transport = _transport(process)
    transport.start()
    transport.send("ping", {"value": 7}, request_id="r1")
    message = transport.read(timeout_s=1)
    transport.close()
    assert message.kind == "ready"
    assert message.value["request_id"] == "r1"
    assert json.loads(process.stdin.getvalue()) == {"cmd": "ping", "request_id": "r1", "value": 7}


def test_generic_transport_applies_only_explicit_environment_overrides() -> None:
    process = _ExitedProcess("")
    captured = {}
    transport = JsonlProcessTransport(
        spec=JsonlProcessSpec(("worker",), "."),
        operating_system=LocalOperatingSystemRoute(),
        task_group=make_task_group("environment-jsonl-env"),
        transport_identity="env-test",
        process_factory=lambda _command, **options: captured.update(options) or process,
        environment_overrides={"NOE_ENV_TEST": "frozen"},
    )
    transport.start()
    try:
        assert captured["env"]["NOE_ENV_TEST"] == "frozen"
    finally:
        transport.close()


def test_generic_transport_has_provider_neutral_error_identity() -> None:
    transport = _transport(_ExitedProcess("not-json\n"))
    transport.start()
    with pytest.raises(JsonlProcessError) as raised:
        transport.read(timeout_s=1)
    assert raised.value.phase == "decode"
    assert raised.value.cause_code == "BRIDGE_INVALID_JSON"
    assert str(raised.value).startswith("JSONL process decode failed")
    transport.close()
