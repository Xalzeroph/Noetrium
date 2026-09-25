from __future__ import annotations

from noetrium_platform.composition.operator.maintenance_wiring.cli import main as manage_main
from noetrium_platform.product.operator.runtime.research_cli import run_research_cli
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
)

from .cli import main as diagnose_main
from .project_experience import build_project_facade
from noetrium_platform.composition.operator.project import load_project_research_os


def main(argv: list[str] | None = None) -> int:
    concurrency_runtime = build_execution_concurrency_runtime(
        blocking_io_thread_name_prefix="operator-research-blocking-io",
        timer_name="operator-research-timer",
    )
    task_group = concurrency_runtime.open_task_group("operator-research")
    try:
        command_runner = build_local_command_runner(task_group)
        return run_research_cli(
            argv,
            diagnose_main=diagnose_main,
            manage_main=manage_main,
            project_experience=build_project_facade(command_runner),
            project_research_os_loader=load_project_research_os,
        )
    finally:
        concurrency_runtime.close()


__all__ = ["main"]
