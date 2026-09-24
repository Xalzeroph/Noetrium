from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)
from noetrium_platform.infrastructure.resources.directory.runtime import (
    standard_local_directory_layout,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)


@dataclass(frozen=True, slots=True)
class ReproductionFleetExecutionContext:
    """One shared platform runtime for repository fleet authority factories.

    Scientific factories receive this context rather than constructing their own
    Docker, endpoint, compute, environment, model, workspace or execution-pool
    authorities.
    """

    state_root: Path
    runtime: ManagedResearchRuntime

    def __post_init__(self) -> None:
        if type(self.state_root) is not Path:
            raise TypeError("fleet execution context state_root must be pathlib.Path")
        if not isinstance(self.runtime, ManagedResearchRuntime):
            raise TypeError(
                "fleet execution context runtime must be ManagedResearchRuntime"
            )

    @property
    def execution_pool(self):
        return self.runtime.execution_pool

    @property
    def management(self):
        return self.runtime.management

    @property
    def resources(self):
        return self.runtime.resources

    @property
    def model_replica_pool(self):
        return self.runtime.model_replica_pool


@contextmanager
def open_local_reproduction_fleet_execution_context(
    state_root: Path,
    *,
    start_background_controllers: bool,
) -> Iterator[ReproductionFleetExecutionContext]:
    """Open the one local platform runtime used by a fleet process."""

    if type(state_root) is not Path:
        raise TypeError("fleet execution state_root must be pathlib.Path")
    resolved_root = state_root.expanduser().absolute()
    platform_root = resolved_root / "platform-runtime"
    runtime_lock = InterprocessFileLock(
        platform_root / "locks" / "fleet-runtime.lock",
        blocking=False,
    )

    with runtime_lock:
        runtime = build_local_managed_research_runtime(
            standard_local_directory_layout(platform_root),
            start_background_controllers=start_background_controllers,
        )
        context = ReproductionFleetExecutionContext(
            state_root=resolved_root,
            runtime=runtime,
        )
        try:
            yield context
        except BaseException as primary:
            cleanup_errors: list[BaseException] = []
            quiesced = False
            try:
                runtime.quiesce_background_controllers()
                quiesced = True
            except BaseException as exc:
                cleanup_errors.append(exc)
            if quiesced:
                try:
                    runtime.resources.shutdown_cleanup()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                runtime.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
            if cleanup_errors:
                raise ExceptionGroup(
                    "fleet execution and shutdown cleanup failed",
                    [primary, *cleanup_errors],
                )
            raise
        else:
            cleanup_errors: list[BaseException] = []
            quiesced = False
            try:
                runtime.quiesce_background_controllers()
                quiesced = True
            except BaseException as exc:
                cleanup_errors.append(exc)
            if quiesced:
                try:
                    runtime.resources.shutdown_cleanup()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                runtime.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
            if cleanup_errors:
                raise ExceptionGroup(
                    "fleet shutdown cleanup failed",
                    cleanup_errors,
                )


__all__ = [
    "ReproductionFleetExecutionContext",
    "open_local_reproduction_fleet_execution_context",
]
