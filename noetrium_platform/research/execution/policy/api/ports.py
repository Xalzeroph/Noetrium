from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    ExecutionLaneKind,
    ExecutionPermitLeasePort,
)

from .contracts import AdmissionIdentity, AdmissionIntent, AdmissionTopologySnapshot


class ExecutionAdmissionPort(Protocol):
    def register_group(
        self,
        group_id: str,
        *,
        identity: AdmissionIdentity,
        intent: AdmissionIntent = AdmissionIntent(),
    ) -> None: ...

    def unregister_group(self, group_id: str) -> None: ...

    def acquire(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> ExecutionPermitLeasePort: ...

    def snapshot(self) -> AdmissionTopologySnapshot: ...
    def close(self) -> None: ...
