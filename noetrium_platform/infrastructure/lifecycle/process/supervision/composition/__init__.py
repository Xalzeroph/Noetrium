from .default import compose
from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime import AsyncLocalCommandRunner, AsyncProcessCommandRunner, AsyncProcessSupervisor
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessTerminationPolicy


def build_local_command_runner(task_group, *, default_timeout_seconds: float = 3600.0) -> AsyncLocalCommandRunner:
    return AsyncLocalCommandRunner(
        build_process_command_runner(task_group),
        default_timeout_seconds=default_timeout_seconds,
    )


def build_process_command_runner(task_group) -> AsyncProcessCommandRunner:
    return AsyncProcessCommandRunner(task_group)


def build_process_supervisor(
    task_group,
    *,
    policy: ProcessTerminationPolicy | None = None,
    termination_hook=None,
    task_namespace: str | None = None,
) -> AsyncProcessSupervisor:
    return AsyncProcessSupervisor(
        task_group, policy, termination_hook, task_namespace=task_namespace
    )


__all__ = ["build_local_command_runner", "build_process_command_runner", "build_process_supervisor", "compose"]
