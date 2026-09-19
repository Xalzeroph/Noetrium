from __future__ import annotations

from noetrium_platform.capabilities.model.deployment.api import ModelDesiredState

from .context import ManagementCommandContext
from .deployment_spec import deployment_from_json, deployment_selector


def dispatch_deployment_action(
    args: object,
    context: ManagementCommandContext,
) -> tuple[bool, object]:
    catalog = context.models.deployment_catalog
    runtime = context.models.deployment_runtime
    fleet = context.models.fleet
    logs = context.models.deployment_logs
    resources = context.models.resources
    action = getattr(args, "action")

    if action == "put-json":
        return True, catalog.put_deployment(deployment_from_json(args.path))
    if action == "list":
        return True, catalog.select(deployment_selector(args))
    if action == "desire":
        return True, catalog.set_desired_state(
            args.deployment_id, ModelDesiredState(args.state)
        )
    if action == "desire-all":
        return True, catalog.set_desired_state_selected(
            deployment_selector(args), ModelDesiredState(args.state)
        )
    if action == "start":
        return True, runtime.start(args.deployment_id)
    if action == "stop":
        return True, runtime.stop(args.deployment_id)
    if action == "restart":
        return True, runtime.restart(args.deployment_id)
    if action == "set-gpus":
        return True, catalog.set_gpu_devices(args.deployment_id, tuple(args.gpu_devices))
    if action == "set-env":
        return True, catalog.set_python_environment(args.deployment_id, args.environment_id)
    if action == "status":
        return True, runtime.status(args.deployment_id)
    if action == "remove":
        return True, {"removed": runtime.remove_deployment(args.deployment_id)}
    if action == "status-all":
        return True, fleet.status_all()
    if action == "reconcile":
        return True, fleet.reconcile()
    if action == "start-all":
        return True, fleet.start_all()
    if action == "stop-all":
        return True, fleet.stop_all()
    if action == "gpu":
        return True, resources.gpu_allocations()
    if action == "gpu-conflicts":
        return True, resources.gpu_conflicts()
    if action == "gpu-runtime":
        return True, resources.gpu_runtime()
    if action == "gpu-candidates":
        return True, resources.gpu_candidates(
            count=args.count,
            min_free_memory_mb=args.min_free_mb,
            max_utilization_percent=args.max_utilization,
        )
    if action == "env-usage":
        return True, resources.environment_usage()
    if action == "gpu-processes":
        return True, resources.gpu_process_bindings()
    if action == "logs":
        return True, logs.logs(args.deployment_id)
    if action == "tail":
        return True, logs.tail_logs(
            args.deployment_id,
            stream=args.stream,
            max_bytes=args.max_bytes,
        )
    return False, None


__all__ = ["dispatch_deployment_action"]
