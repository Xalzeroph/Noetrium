from __future__ import annotations

from dataclasses import dataclass
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.substrate.api import OperatingSystemRoute, ProcessSupervisorPort

from ..api import MinecraftDiagnosticsPort, MinecraftEnvironmentSpec, MinecraftCheckpointPort
from ..providers.jsonl_bridge import JsonlMinecraftBridge
from ..providers.jsonl_transport import ProcessFactory
from ..runtime import MinecraftEnvironmentImplementation, MinecraftEnvironmentRuntime


@dataclass(frozen=True, slots=True)
class MinecraftEnvironmentAssembly:
    """One explicit MC composition result consumed by a participant binder."""

    implementation: MinecraftEnvironmentImplementation
    runtime: MinecraftEnvironmentRuntime


def compose_minecraft_environment(
    spec: MinecraftEnvironmentSpec,
    *,
    operating_system: OperatingSystemRoute,
    diagnostics: MinecraftDiagnosticsPort | None = None,
    checkpoint: MinecraftCheckpointPort | None = None,
    process_factory: ProcessFactory | None = None,
    process_supervisor: ProcessSupervisorPort,
    task_group: TaskGroupPort,
) -> MinecraftEnvironmentAssembly:
    """Bind the replaceable JSONL provider to the MC environment runtime.

    This function is the only MC-owned place that knows the concrete default
    provider. Projects may pass another bridge factory at a higher composition
    root without changing MC contracts or the session runtime.
    """

    def bridge_factory(environment_spec: MinecraftEnvironmentSpec):
        return JsonlMinecraftBridge(
            endpoint=environment_spec.endpoint,
            spec=environment_spec.bridge,
            agent=environment_spec.agent,
            operating_system=operating_system,
            process_factory=process_factory,
            process_supervisor=process_supervisor,
            diagnostics=diagnostics,
            task_group=task_group,
        )

    implementation = MinecraftEnvironmentImplementation(
        spec=spec,
        bridge_factory=bridge_factory,
        checkpoint=checkpoint,
    )
    runtime = MinecraftEnvironmentRuntime(bridge_factory, diagnostics=diagnostics)
    return MinecraftEnvironmentAssembly(implementation=implementation, runtime=runtime)


__all__ = ["MinecraftEnvironmentAssembly", "compose_minecraft_environment"]
