from __future__ import annotations

from noetrium_platform.product.operator.runtime.research_cli import run_research_cli
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime, build_scheduling_authority
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
)

from .project_experience import build_project_facade
from noetrium_platform.composition.operator.project import load_research_root


def main(argv: list[str] | None = None) -> int:
    concurrency_runtime = build_execution_concurrency_runtime(scheduling_authority=build_scheduling_authority(),
        blocking_io_thread_name_prefix="operator-research-blocking-io",
        timer_name="operator-research-timer",
    )
    task_group = concurrency_runtime.open_task_group("operator-research")
    try:
        command_runner = build_local_command_runner(task_group)
        return run_research_cli(
            argv,
            project_experience=build_project_facade(command_runner),
            research_root_loader=load_research_root,
        )
    finally:
        concurrency_runtime.close()


__all__ = ["main"]
