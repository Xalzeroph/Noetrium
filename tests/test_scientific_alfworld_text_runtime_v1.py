from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    ActionRequest,
)
from noetrium_platform.composition.environment_capabilities import EnvironmentSessionCapabilityAdapter
from noetrium_platform.capabilities.environment.providers import JsonlProcessMessage
from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, ExecutionContext
from research.benchmarks.alfworld.runtime import AlfworldTextRuntimeSpec, AlfworldTextSession
from research.benchmarks.alfworld.runtime.session import _ManagedDockerWorkerTransport


class _FakeWorkerTransport:
    def __init__(self) -> None:
        self._started = False
        self._last = None
        self.actions: list[str] = []
        self.commands: list[str] = []

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        self._started = True

    def send(self, command, payload, *, request_id: str) -> None:
        assert self._started
        self.commands.append(command)
        self._last = (command, dict(payload), request_id)

    def read(self, *, timeout_s: float) -> JsonlProcessMessage:
        assert timeout_s > 0
        command, payload, request_id = self._last
        if command == "reset":
            self.actions = []
            return JsonlProcessMessage(
                "reset",
                {
                    "type": "reset",
                    "request_id": request_id,
                    "observation": "Welcome.\n\nYou are in a kitchen.",
                    "done": False,
                    "won": False,
                    "gamefile": payload["gamefile"],
                    "admissible_commands": ["look", "finish"],
                },
            )
        if command == "step":
            action = str(payload["action"])
            self.actions.append(action)
            won = action == "finish"
            return JsonlProcessMessage(
                "step",
                {
                    "type": "step",
                    "request_id": request_id,
                    "observation": "state:" + "|".join(self.actions),
                    "done": won,
                    "won": won,
                    "gamefile": "pick_and_place_simple/task-1/game.tw-pddl",
                    "admissible_commands": ["look", "finish"],
                },
            )
        if command == "close":
            return JsonlProcessMessage("closed", {"type": "closed", "request_id": request_id})
        raise AssertionError(command)

    def close(self) -> None:
        self._started = False


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        study_id="react-alfworld",
        task_id="alfworld-task-1",
        decision_cycle_id="cycle-1",
    )


def _spec(tmp_path: Path) -> AlfworldTextRuntimeSpec:
    data_root = tmp_path / "data"
    recovery_root = tmp_path / "recovery"
    data_root.mkdir(exist_ok=True)
    recovery_root.mkdir(exist_ok=True)
    return AlfworldTextRuntimeSpec(
        image="alfworld-test:image",
        runtime_artifact_digest="a" * 64,
        data_root=str(data_root),
        task_gamefile="pick_and_place_simple/task-1/game.tw-pddl",
        recovery_root=str(recovery_root),
        session_id="session-1",
    )


def _session(tmp_path: Path, instances: list[_FakeWorkerTransport]) -> AlfworldTextSession:
    def factory() -> _FakeWorkerTransport:
        worker = _FakeWorkerTransport()
        instances.append(worker)
        return worker

    return AlfworldTextSession(_spec(tmp_path), transport_factory=factory)


def test_session_commits_action_once_and_replays_durable_state_after_restart(tmp_path: Path) -> None:
    instances: list[_FakeWorkerTransport] = []
    session = _session(tmp_path, instances)
    context = _context()
    request = ActionRequest("action-1", "command", {"text": "look"}, context)
    handle = session.prepare_action_recovery(request, context)
    first = session.execute_prepared_action(request, handle)
    duplicate = session.execute_prepared_action(request, handle)

    assert first.accepted is True
    assert first.effect is not None
    assert first.effect.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert first.observation is not None
    assert first.observation.payload["text"] == "state:look"
    assert duplicate.observation == first.observation
    assert instances[0].actions == ["look"]
    checkpoint = session.checkpoint()
    session.close()

    restarted = _session(tmp_path, instances)
    observed = restarted.observe(context)
    assert observed.payload["text"] == "state:look"
    assert instances[1].actions == ["look"]
    assert restarted.checkpoint() == checkpoint
    restarted.close()


def test_uncommitted_prepared_action_reconciles_not_applied_after_reset_replay(tmp_path: Path) -> None:
    instances: list[_FakeWorkerTransport] = []
    session = _session(tmp_path, instances)
    context = _context()
    request = ActionRequest("action-pending", "command", {"text": "finish"}, context)
    handle = session.prepare_action_recovery(request, context)

    reconciliation = session.reconcile_prepared_action(handle, context)

    assert reconciliation.disposition is ActionReconciliationDisposition.NOT_APPLIED
    assert reconciliation.result is not None
    assert reconciliation.result.accepted is False
    assert reconciliation.result.effect is not None
    assert reconciliation.result.effect.certainty is EffectCertainty.NO_EFFECT
    assert len(instances) == 2
    assert instances[-1].actions == []
    session.close()


def test_generic_environment_capability_adapter_executes_real_session_contract(tmp_path: Path) -> None:
    instances: list[_FakeWorkerTransport] = []
    session = _session(tmp_path, instances)
    adapter = EnvironmentSessionCapabilityAdapter(session)
    context = _context()
    request = CapabilityRequest(
        capability_id="environment.act",
        payload={"action_type": "command", "payload": {"text": "finish"}},
        context=context,
        idempotency_key="finish-1",
    )

    prepared = adapter.prepare_capability_effect(request)
    result = adapter.execute_prepared_capability(request, prepared)

    assert result.payload["accepted"] is True
    observation = result.payload["observation"]
    assert observation["payload"]["done"] is True
    assert observation["payload"]["info"]["won"] is True
    assert result.effect is not None
    assert result.effect.certainty is EffectCertainty.EFFECT_CONFIRMED
    adapter.close()


def test_managed_docker_close_keeps_lower_fences_when_worker_stop_fails() -> None:
    class Delegate:
        def __init__(self) -> None:
            self.close_calls = 0

        @property
        def started(self) -> bool:
            return True

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("worker still live")

    class Guard:
        def __init__(self) -> None:
            self.close_calls = 0

        def start(self) -> None:
            return None

        def assert_healthy(self) -> None:
            return None

        def close(self) -> None:
            self.close_calls += 1

    class Containers:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self, lease) -> None:
            del lease
            self.release_calls += 1

    delegate = Delegate()
    guard = Guard()
    containers = Containers()
    transport = _ManagedDockerWorkerTransport(
        delegate,
        container_leases=containers,
        lease=object(),
        lease_guard=guard,
    )

    with pytest.raises(BaseExceptionGroup, match="before physical convergence"):
        transport.close()

    assert delegate.close_calls == 1
    assert guard.close_calls == 0
    assert containers.release_calls == 0

    transport.close()

    assert delegate.close_calls == 2
    assert guard.close_calls == 1
    assert containers.release_calls == 1


def test_managed_docker_close_retries_container_release_without_reclosing_worker() -> None:
    class Delegate:
        def __init__(self) -> None:
            self.close_calls = 0

        @property
        def started(self) -> bool:
            return True

        def close(self) -> None:
            self.close_calls += 1

    class Guard:
        def __init__(self) -> None:
            self.close_calls = 0

        def start(self) -> None:
            return None

        def assert_healthy(self) -> None:
            return None

        def close(self) -> None:
            self.close_calls += 1

    class Containers:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self, lease) -> None:
            del lease
            self.release_calls += 1
            if self.release_calls == 1:
                raise RuntimeError("durable release failed")

    delegate = Delegate()
    guard = Guard()
    containers = Containers()
    transport = _ManagedDockerWorkerTransport(
        delegate,
        container_leases=containers,
        lease=object(),
        lease_guard=guard,
    )

    with pytest.raises(BaseExceptionGroup, match="releasing container"):
        transport.close()

    transport.close()

    assert delegate.close_calls == 1
    assert guard.close_calls == 1
    assert containers.release_calls == 2
