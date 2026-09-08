from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.research.execution.api import DeploymentStatusIdentity
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionBackendConfig, PersistentSessionStatusConfig
from .runtime_status_contracts import RuntimeStatusLayout, ServiceStatusBinding


def load_runtime_status_layout(path: Path) -> RuntimeStatusLayout:
    data = json.loads(path.read_text(encoding="utf-8"))
    deployments = tuple(DeploymentStatusIdentity(**row) for row in data["deployments"])
    services = tuple(
        ServiceStatusBinding(
            str(row["service_id"]),
            Path(row["state_path"]),
            Path(row["start_intent_root"]),
        )
        for row in data.get("services", ())
    )
    session_data = data.get("server_session")
    server_session = None
    if session_data is not None:
        backend_data = dict(session_data["backend"])
        options_data = dict(backend_data.get("options", {}))
        options = tuple(sorted((str(key), str(value)) for key, value in options_data.items()))
        server_session = PersistentSessionStatusConfig(
            binding_root=Path(session_data["binding_root"]),
            session_name=str(session_data["session_name"]),
            backend=PersistentSessionBackendConfig(str(backend_data["id"]), options),
        )
    return RuntimeStatusLayout(
        runtime_state=Path(data["runtime_state"]),
        runtime_history=Path(data["runtime_history"]),
        heartbeat_root=Path(data["heartbeat_root"]),
        recovery_lease=Path(data["recovery_lease"]),
        forensic_root=Path(data["forensic_root"]),
        deployments=deployments,
        services=services,
        heartbeat_max_age_seconds=float(data.get("heartbeat_max_age_seconds", 30.0)),
        server_session=server_session,
    )


__all__ = ["load_runtime_status_layout"]
