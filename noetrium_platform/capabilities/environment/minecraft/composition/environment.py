from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.substrate.api import OperatingSystemRoute, ProcessSupervisorPort

from ..api import (
    MinecraftCheckpointPort,
    MinecraftDiagnosticsPort,
    MinecraftEnvironmentRuntimeBinding,
    minecraft_environment_agent,
    require_minecraft_environment,
)
from ..providers.jsonl_bridge import JsonlMinecraftBridge
from ..providers.jsonl_transport import ProcessFactory
from ..runtime import MinecraftEnvironmentImplementation, MinecraftEnvironmentRuntime


@dataclass(frozen=True, slots=True)
class MinecraftEnvironmentAssembly:
    """One explicit MC runtime composition consumed by a participant binder."""

    implementation: MinecraftEnvironmentImplementation
    runtime: MinecraftEnvironmentRuntime


def compose_minecraft_environment(
    environment: NoetriumUnit,
    runtime_binding: MinecraftEnvironmentRuntimeBinding,
    *,
    operating_system: OperatingSystemRoute,
    diagnostics: MinecraftDiagnosticsPort | None = None,
    checkpoint: MinecraftCheckpointPort | None = None,
    process_factory: ProcessFactory | None = None,
    process_supervisor: ProcessSupervisorPort,
    task_group: TaskGroupPort,
) -> MinecraftEnvironmentAssembly:
    """Bind one immutable Minecraft environment Unit to physical runtime facts."""

    environment = require_minecraft_environment(environment)
    if not isinstance(runtime_binding, MinecraftEnvironmentRuntimeBinding):
        raise TypeError("Minecraft composition requires runtime binding")

    def bridge_factory(
        environment_unit: NoetriumUnit,
        binding: MinecraftEnvironmentRuntimeBinding,
    ):
        environment_unit = require_minecraft_environment(environment_unit)
        if not isinstance(binding, MinecraftEnvironmentRuntimeBinding):
            raise TypeError("Minecraft bridge requires runtime binding")
        return JsonlMinecraftBridge(
            endpoint=binding.endpoint,
            spec=binding.bridge,
            agent=minecraft_environment_agent(environment_unit),
            operating_system=operating_system,
            process_factory=process_factory,
            process_supervisor=process_supervisor,
            diagnostics=diagnostics,
            task_group=task_group,
        )

    implementation = MinecraftEnvironmentImplementation(
        environment=environment,
        runtime_binding=runtime_binding,
        bridge_factory=bridge_factory,
        checkpoint=checkpoint,
    )
    runtime = MinecraftEnvironmentRuntime(bridge_factory, diagnostics=diagnostics)
    return MinecraftEnvironmentAssembly(implementation=implementation, runtime=runtime)


__all__ = ["MinecraftEnvironmentAssembly", "compose_minecraft_environment"]
