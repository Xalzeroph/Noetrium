from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from noetrium_platform.infrastructure.lifecycle.python.api import EnvironmentCommandResult
from noetrium_platform.composition.model_management import build_local_management_plane
from noetrium_platform.foundation.kernel.concurrency.api import TaskFailurePolicy, TaskGroupPort
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime
from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.product.operator.api.json_rendering import render_json
from .management import DISPATCH, ManagementCommandContext, register_all



def _emit(value, *, stream=None) -> None:
    print(render_json(value), file=stream or sys.stdout)


def _load_config(config_path: Path) -> tuple[dict, DirectoryLayout]:
    data = json.loads(config_path.read_text("utf-8"))
    layout = DirectoryLayout(
        **{
            key: Path(value).expanduser().resolve()
            for key, value in data["directories"].items()
        }
    )
    return data, layout


def _load_context(
    data: dict,
    layout: DirectoryLayout,
    task_group: TaskGroupPort,
) -> ManagementCommandContext:
    base_environment = tuple(sorted((str(k), str(v)) for k, v in data.get("service_environment", {}).items()))
    source_config = data.get("model_sources", {})
    model_source_environment = tuple(
        sorted((str(key), str(value)) for key, value in data.get("model_source_environment", {}).items())
    )
    storage_pools = {
        str(pool_id): Path(value).expanduser().resolve()
        for pool_id, value in data.get("model_storage_pools", {}).items()
    }
    plane = build_local_management_plane(
        layout,
        base_service_environment=base_environment,
        model_source_environment=model_source_environment,
        huggingface_cli=str(source_config.get("huggingface_cli", "hf")),
        model_storage_pools=storage_pools,
        task_group=task_group,
    )
    return ManagementCommandContext(
        plane.scopes,
        plane.directories,
        plane.execution_environments,
        plane.python_environments,
        plane.models,
        plane.deployment_qualification,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noetrium-manage")
    parser.add_argument("--config", required=True, type=Path)
    groups = parser.add_subparsers(dest="group", required=True)
    register_all(groups)
    return parser


def _require_command_success(result):
    """Turn a managed subprocess failure into a failed management command."""

    if isinstance(result, EnvironmentCommandResult) and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"managed environment command failed with exit code {result.returncode}{suffix}"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    runtime_lock: InterprocessFileLock | None = None
    concurrency_runtime = None
    task_group = None
    lock_acquired = False
    try:
        try:
            data, layout = _load_config(args.config)
            # Standalone maintenance is an exclusive state-root owner, not a
            # side channel around ManagedResearchRuntime. Acquire the same lock
            # before constructing concurrency/controller/provider authorities so
            # a losing contender cannot start heartbeat/reconcile/physical work.
            runtime_lock = InterprocessFileLock(
                layout.locks / "managed-research-runtime.lock",
                blocking=False,
            )
            runtime_lock.__enter__()
            lock_acquired = True

            concurrency_runtime = build_execution_concurrency_runtime()
            task_group = concurrency_runtime.open_task_group(
                "management-cli",
                failure_policy=TaskFailurePolicy.COLLECT_ALL,
            )
            context = _load_context(data, layout, task_group)
            result = _require_command_success(DISPATCH[args.group](args, context))
        except (
            KeyError,
            ValueError,
            FileNotFoundError,
            FileExistsError,
            RuntimeError,
        ) as exc:
            descriptor = describe_exception(exc)
            _emit(
                {
                    "ok": False,
                    "error_type": descriptor.error_type,
                    "error": descriptor.safe_message,
                    "error_digest": descriptor.error_digest,
                },
                stream=sys.stderr,
            )
            return 2
        _emit({"ok": True, "result": result})
        return 0
    finally:
        # Keep exclusive authority through child/controller convergence. The
        # kernel lock is always the final lifetime object released.
        if task_group is not None:
            task_group.close()
        if concurrency_runtime is not None:
            concurrency_runtime.close()
        if lock_acquired and runtime_lock is not None:
            runtime_lock.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
