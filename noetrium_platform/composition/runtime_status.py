from __future__ import annotations

from noetrium_platform.infrastructure.reliability.diagnostics.runtime.status_projection import ForensicStatusProbe
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort
from .runtime_status_contracts import RuntimeStatusLayout
from noetrium_platform.evidence.observability.status.runtime import PlatformStatusService
from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat_storage import FileServiceHeartbeatStore
from noetrium_platform.infrastructure.lifecycle.launch_control.history import RuntimeHistory
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_history_storage import FileRuntimeHistoryStorage
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_state_storage import FileRuntimeControlStateStore
from noetrium_platform.infrastructure.lifecycle.launch_control.model_deployment_status import ModelDeploymentStatusProbe
from noetrium_platform.infrastructure.reliability.recovery.composition import (
    compose_recovery_lease_status_probe,
    compose_sqlite_recovery_lease,
)
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_transaction_status import RuntimeTransactionStatusProbe
from noetrium_platform.infrastructure.lifecycle.launch_control.status_readers import (
    RuntimeControlStatusReader,
    ServiceHeartbeatStatusReader,
)
from noetrium_platform.infrastructure.lifecycle.session.runtime import default_persistent_session_backend_registry
from noetrium_platform.infrastructure.lifecycle.session.runtime.health_projection import PersistentSessionHealthProbe
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.status_projection import ServiceOperationalStatusProbe
from noetrium_platform.infrastructure.lifecycle.service.runtime.status_reader import ServiceOperationalStatusReader


def build_runtime_status_service(
    layout: RuntimeStatusLayout,
    forensic_evidence: DiagnosticEvidencePort,
    *,
    task_group: TaskGroupPort,
) -> PlatformStatusService:
    """Concrete IO assembly for otherwise independent read-only subsystem probes."""

    runtime_reader = RuntimeControlStatusReader(
        FileRuntimeControlStateStore(layout.runtime_state),
        RuntimeHistory(FileRuntimeHistoryStorage(layout.runtime_history)),
    )
    heartbeat_reader = ServiceHeartbeatStatusReader(FileServiceHeartbeatStore(layout.heartbeat_root))
    probes = [
        RuntimeTransactionStatusProbe(runtime_reader),
        compose_recovery_lease_status_probe(compose_sqlite_recovery_lease(layout.resource_authority)),
    ]

    registry = default_persistent_session_backend_registry(task_group)
    if layout.server_session is not None:
        probes.insert(
            0,
            PersistentSessionHealthProbe(registry.build_status_probe(layout.server_session)),
        )

    probes.extend(
        ModelDeploymentStatusProbe(
            deployment,
            heartbeat_reader,
            heartbeat_max_age_seconds=layout.heartbeat_max_age_seconds,
        )
        for deployment in sorted(layout.deployments, key=lambda item: item.deployment_id)
    )
    probes.extend(
        ServiceOperationalStatusProbe(
            binding.service_id,
            ServiceOperationalStatusReader(
                FileServiceStateStore(binding.state_path),
                DirectoryServiceStartIntentStore(binding.start_intent_root),
            ),
        )
        for binding in sorted(layout.services, key=lambda item: item.service_id)
    )
    probes.append(ForensicStatusProbe(forensic_evidence))
    return PlatformStatusService(probes)


__all__ = ["build_runtime_status_service"]
