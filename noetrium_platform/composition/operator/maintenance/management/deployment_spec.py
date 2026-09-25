from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentSelector,
    ModelDeploymentSpec,
    ModelDesiredState,
)

from .scope_args import scope_from_json


def deployment_from_json(path: Path) -> ModelDeploymentSpec:
    data = json.loads(path.read_text("utf-8"))
    return ModelDeploymentSpec(
        deployment_id=data["deployment_id"],
        scope=scope_from_json(data.get("scope")),
        service_id=data.get("service_id", f"model:{data['deployment_id']}"),
        model_id=data["model_id"],
        engine=data.get("engine", "custom"),
        executable=data["executable"],
        argv=tuple(data.get("argv", ())),
        cwd=Path(data["cwd"]).expanduser().resolve(),
        python_environment_id=data.get("python_environment_id"),
        gpu_devices=tuple(str(value) for value in data.get("gpu_devices", ())),
        environment=tuple(
            sorted((str(key), str(value)) for key, value in data.get("environment", {}).items())
        ),
        readiness_url=data.get("readiness_url"),
        readiness_timeout_s=float(data.get("readiness_timeout_s", 120.0)),
        stop_timeout_s=float(data.get("stop_timeout_s", 30.0)),
        heartbeat_interval_s=float(data.get("heartbeat_interval_s", 10.0)),
        desired_state=ModelDesiredState(data.get("desired_state", "stopped")),
        tags=tuple(sorted({str(value) for value in data.get("tags", ()) if str(value)})),
    )


def deployment_selector(args: object) -> ModelDeploymentSelector:
    return ModelDeploymentSelector(
        tags=tuple(getattr(args, "tag", ())),
        model_id=getattr(args, "model", None),
        engine=getattr(args, "engine", None),
        python_environment_id=getattr(args, "env", None),
    )


__all__ = ["deployment_from_json", "deployment_selector"]
