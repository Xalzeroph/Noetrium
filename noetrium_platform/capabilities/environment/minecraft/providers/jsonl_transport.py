from __future__ import annotations

import os
from pathlib import Path

from noetrium_platform.capabilities.environment.providers.jsonl_process import (
    JsonlProcess,
    JsonlProcessError,
    JsonlProcessMessage,
    JsonlProcessSpec,
    JsonlProcessTransport as _JsonlProcessTransport,
    ProcessFactory,
    safe_exception_message,
)
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.substrate.api import OperatingSystemRoute, ProcessSupervisorPort

from ..api import MinecraftBridgeSpec


class MinecraftBridgeError(JsonlProcessError):
    """Minecraft protocol transport failure with stable phase/cause identity."""

    error_prefix = "Minecraft bridge"


JsonlBridgeMessage = JsonlProcessMessage


def _node_path_overrides() -> dict[str, str]:
    bridge_root = os.environ.get("MC_BRIDGE_DIR", "").strip()
    if not bridge_root:
        return {}
    node_modules = Path(bridge_root) / "node_modules"
    if not node_modules.is_dir():
        return {}
    rows = [str(node_modules)]
    existing = os.environ.get("NODE_PATH", "").strip()
    if existing:
        rows.append(existing)
    return {"NODE_PATH": os.pathsep.join(rows)}


class JsonlProcessTransport(_JsonlProcessTransport):
    """Minecraft binding over the provider-neutral JSONL subprocess transport."""

    def __init__(
        self,
        *,
        spec: MinecraftBridgeSpec,
        operating_system: OperatingSystemRoute,
        task_group: TaskGroupPort,
        bridge_identity: str,
        process_factory: ProcessFactory | None = None,
        process_supervisor: ProcessSupervisorPort,
        failure_reporter=None,
        stderr_tail_lines: int = 300,
    ) -> None:
        if not isinstance(spec, MinecraftBridgeSpec):
            raise TypeError("Minecraft JSONL transport requires MinecraftBridgeSpec")
        self.minecraft_spec = spec
        super().__init__(
            spec=JsonlProcessSpec(
                command=spec.command,
                cwd=spec.cwd,
                stdout_queue_capacity=spec.stdout_queue_capacity,
            ),
            operating_system=operating_system,
            task_group=task_group,
            transport_identity=bridge_identity,
            process_factory=process_factory,
            process_supervisor=process_supervisor,
            failure_reporter=failure_reporter,
            stderr_tail_lines=stderr_tail_lines,
            environment_overrides=_node_path_overrides(),
            task_namespace="minecraft-bridge",
            error_type=MinecraftBridgeError,
        )


__all__ = [
    "JsonlBridgeMessage",
    "JsonlProcess",
    "JsonlProcessTransport",
    "MinecraftBridgeError",
    "ProcessFactory",
    "safe_exception_message",
]
