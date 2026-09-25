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
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_supervisor
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
    task_group = make_task_group("environment-jsonl-generic")
    return JsonlProcessTransport(
        spec=JsonlProcessSpec(("worker",), "."),
        operating_system=LocalOperatingSystemRoute(),
        task_group=task_group,
        process_supervisor=build_process_supervisor(task_group),
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
    task_group = make_task_group("environment-jsonl-env")
    transport = JsonlProcessTransport(
        spec=JsonlProcessSpec(("worker",), "."),
        operating_system=LocalOperatingSystemRoute(),
        task_group=task_group,
        process_supervisor=build_process_supervisor(task_group),
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


class _LiveProcess(_ExitedProcess):
    def __init__(self) -> None:
        super().__init__("")
        self.alive = True
        self.pid = 912

    def poll(self):
        return None if self.alive else 0


class _Result:
    def __init__(self, *, error=None, value=None) -> None:
        self.error = error
        self.value = value

    def result(self, timeout=None):
        del timeout
        if self.error is not None:
            raise self.error
        return self.value


class _FlakyTerminationSupervisor:
    def __init__(self, process: _LiveProcess) -> None:
        self.process = process
        self.terminate_calls = 0

    def await_exit(self, *args, **kwargs):
        del args, kwargs
        return _Result(error=TimeoutError("process still live"))

    def terminate(self, *args, **kwargs):
        del args, kwargs
        self.terminate_calls += 1
        if self.terminate_calls <= 2:
            return _Result(error=TimeoutError("termination did not converge"))
        self.process.alive = False
        return _Result(value=None)


def test_close_retains_exact_process_identity_until_physical_exit_is_proven() -> None:
    process = _LiveProcess()
    supervisor = _FlakyTerminationSupervisor(process)
    task_group = make_task_group("environment-jsonl-close-retry")
    transport = JsonlProcessTransport(
        spec=JsonlProcessSpec(("worker",), "."),
        operating_system=LocalOperatingSystemRoute(),
        task_group=task_group,
        process_supervisor=supervisor,
        transport_identity="close-retry",
        process_factory=lambda _command, **_options: process,
    )
    transport.start()

    with pytest.raises(TimeoutError, match="termination did not converge"):
        transport.close()

    assert transport.started is True
    assert transport.process_id == 912

    transport.close()

    assert transport.started is False
    assert transport.process_id is None
    assert supervisor.terminate_calls == 3



class _FailingSubmitGroup:
    def __init__(self, *, fail_on: int) -> None:
        self.fail_on = fail_on
        self.calls = 0

    def submit(self, *args, **kwargs):
        del args, kwargs
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("simulated drain task registration failure")
        return _Result(value=None)


class _ImmediateTerminationSupervisor:
    def __init__(self, process: _LiveProcess) -> None:
        self.process = process
        self.terminate_calls = 0

    def await_exit(self, *args, **kwargs):
        del args, kwargs
        return _Result(error=TimeoutError("process still live"))

    def terminate(self, *args, **kwargs):
        del args, kwargs
        self.terminate_calls += 1
        self.process.alive = False
        return _Result(value=None)


@pytest.mark.parametrize("fail_on", (1, 2))
def test_partial_start_failure_rolls_back_spawned_process(fail_on: int) -> None:
    process = _LiveProcess()
    supervisor = _ImmediateTerminationSupervisor(process)
    task_group = _FailingSubmitGroup(fail_on=fail_on)
    transport = JsonlProcessTransport(
        spec=JsonlProcessSpec(("worker",), "."),
        operating_system=LocalOperatingSystemRoute(),
        task_group=task_group,
        process_supervisor=supervisor,
        transport_identity=f"partial-start-{fail_on}",
        process_factory=lambda _command, **_options: process,
    )

    with pytest.raises(RuntimeError, match="drain task registration failure"):
        transport.start()

    assert process.alive is False
    assert transport.started is False
    assert transport.process_id is None
    assert supervisor.terminate_calls == 1
