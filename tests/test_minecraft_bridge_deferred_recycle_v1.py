from __future__ import annotations

from tests._concurrency_support import make_task_group
from tests._minecraft_environment_cases import (
    _FakeProcess, TEST_OPERATING_SYSTEM, _test_action_wire_identity,
)
from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
)
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import JsonlMinecraftBridge
from noetrium_platform.capabilities.environment.api import ActionRequest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_supervisor


class _RecycleProcess(_FakeProcess):
    def __init__(self, *, recommend_recycle: bool) -> None:
        super().__init__()
        self.recommend_recycle = recommend_recycle

    def _ack(self, command: str, request_id: str | None, **payload):
        if command == "wait" and self.recommend_recycle:
            payload["bridge_recycle_recommended"] = True
        return super()._ack(command, request_id, **payload)


def test_bridge_recycle_is_deferred_until_next_command_boundary() -> None:
    task_group = make_task_group("minecraft-bridge-deferred-recycle")
    processes: list[_RecycleProcess] = []

    def process_factory(_command, **_kwargs):
        process = _RecycleProcess(recommend_recycle=(len(processes) == 0))
        processes.append(process)
        return process

    bridge = JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25567),
        spec=MinecraftBridgeSpec(
            command=("fake-node",), cwd=".", command_timeout_s=1, connect_timeout_s=1
        ),
        agent=MinecraftAgentSpec(version="1.21.6"),
        operating_system=TEST_OPERATING_SYSTEM,
        process_factory=process_factory,
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    bridge.start()
    first_pid = bridge.process_id

    context = ExecutionContext("run", "trace", "span", task_id="task")
    first_request = ActionRequest("a1", "wait", {"ms": 1}, context)
    first = bridge.command(
        "wait", {**_test_action_wire_identity(first_request), "ms": 1}, timeout_s=1
    )
    assert first.acknowledged is True
    assert len(processes) == 1
    assert bridge.process_id == first_pid
    assert processes[0].returncode is None

    second_request = ActionRequest("a2", "wait", {"ms": 1}, context)
    second = bridge.command(
        "wait", {**_test_action_wire_identity(second_request), "ms": 1}, timeout_s=1
    )
    assert second.acknowledged is True
    assert len(processes) == 2
    assert processes[0].returncode == 0
    assert bridge.process_id != first_pid
    assert processes[1].returncode is None

    bridge.close()
    task_group.close()
