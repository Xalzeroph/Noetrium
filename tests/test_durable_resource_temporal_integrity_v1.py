from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes as platform_atomic_replace_bytes
import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime_module
from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLease
from noetrium_platform.infrastructure.reliability.recovery.execution.runtime.file_lock import (
    FileLockedRecoveryExecutionFactory,
)
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocation,
    EndpointAllocationRequest,
    EndpointBindingProof,
    EndpointLeasePolicy,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import AtomicEndpointAllocator
from noetrium_platform.infrastructure.resources.directory.api import ManagedDirectoryKind
from noetrium_platform.infrastructure.resources.directory.runtime.workspaces import LocalWorkspaceManager
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
)
from noetrium_platform.infrastructure.resources.lease.runtime import InMemoryResourceLeaseRegistry
from noetrium_platform.infrastructure.resources.providers import (
    SQLiteEndpointAllocationStore,
    SQLiteResourceLeaseRegistry,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind


class _AvailableProbe:
    def probe(self, endpoint: NetworkEndpoint):
        from noetrium_platform.infrastructure.resources.allocation.api import EndpointProbeResult
        return EndpointProbeResult(endpoint, True, "available")


class _LeaseStateStub:
    def acquire(self, *args, **kwargs): raise AssertionError("must not acquire")
    def renew(self, *args, **kwargs): raise AssertionError("must not renew")
    def assert_owned(self, *args, **kwargs): raise AssertionError("must not inspect")
    def release(self, *args, **kwargs): raise AssertionError("must not release")


class _DirectoryLayoutStub:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self, kind: ManagedDirectoryKind) -> Path:
        path = self._root / kind.value
        path.mkdir(parents=True, exist_ok=True)
        return path


def _resource_lease(*, expires_at: float | None = None) -> ResourceLease:
    return ResourceLease(
        "lease-a",
        ResourceIdentity(ResourceKind.COMPUTE, "host-a"),
        ScopeIdentity(ScopeKind.WORKSPACE, "workspace-a"),
        "temporal integrity",
        expires_at_epoch_s=expires_at,
    )


def test_resource_lease_rejects_non_finite_expiry_and_observation_time() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite positive"):
            _resource_lease(expires_at=value)
    lease = _resource_lease(expires_at=100.0)
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="observation time must be finite"):
            lease.expired_at(value)


def test_resource_lease_authorities_reject_non_finite_ttl_and_clock() -> None:
    resource = ResourceIdentity(ResourceKind.COMPUTE, "host-a")
    memory = InMemoryResourceLeaseRegistry()
    memory.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    lease = ResourceLease("lease-a", resource, PLATFORM_SCOPE, "finite lease")
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite and > 0"):
            memory.acquire(lease, ttl_seconds=value, now=1.0)
        with pytest.raises(ValueError, match="observation time must be finite"):
            memory.acquire(lease, ttl_seconds=10.0, now=value)

    with TemporaryDirectory() as directory:
        database = Path(directory) / "resource.sqlite"
        sqlite = SQLiteResourceLeaseRegistry(database)
        sqlite.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
        for value in (float("nan"), float("inf")):
            with pytest.raises(ValueError, match="finite and > 0"):
                sqlite.acquire(lease, ttl_seconds=value, now=1.0)
            with pytest.raises(ValueError, match="observation time must be finite"):
                sqlite.acquire(lease, ttl_seconds=10.0, now=value)
        granted = sqlite.acquire(lease, ttl_seconds=10.0, now=1.0)
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="observation time must be finite"):
                sqlite.renew(
                    granted.lease_id, fencing_token=granted.fencing_token,
                    ttl_seconds=10.0, now=value,
                )
            with pytest.raises(ValueError, match="observation time must be finite"):
                sqlite.release(granted.lease_id, now=value)
            with pytest.raises(ValueError, match="observation time must be finite"):
                sqlite.reconcile_expired(now=value)


def test_endpoint_temporal_contracts_reject_non_finite_values() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="ttl_seconds must be finite"):
            EndpointLeasePolicy(ttl_seconds=value, renewal_interval_seconds=1.0)
        with pytest.raises(ValueError, match="renewal_interval_seconds must be finite"):
            EndpointLeasePolicy(ttl_seconds=10.0, renewal_interval_seconds=value)
        with pytest.raises(ValueError, match="observation timestamp must be finite"):
            EndpointBindingProof(
                "allocation-a", NetworkEndpoint("127.0.0.1", 25565), 1,
                "a" * 64, value, "listener-evidence",
            )
        with pytest.raises(ValueError, match="lease expiry must be finite"):
            EndpointAllocation(
                "allocation-a", NetworkEndpoint("127.0.0.1", 25565), "lease-a",
                PLATFORM_SCOPE, "finite endpoint", "d" * 64,
                lease_expires_at_epoch_s=value,
            )


def test_endpoint_authorities_reject_non_finite_runtime_budgets() -> None:
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="lease_ttl_seconds must be finite"):
            AtomicEndpointAllocator(
                reservations=object(),  # type: ignore[arg-type]
                probe=_AvailableProbe(),
                lease_ttl_seconds=value,
            )
    with TemporaryDirectory() as directory:
        path = Path(directory) / "endpoint.sqlite"
        store = SQLiteEndpointAllocationStore(path)
        request = EndpointAllocationRequest(
            "allocation-a", PLATFORM_SCOPE, "finite endpoint", "127.0.0.1", (25565,)
        )
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        reserved = allocator.allocate(request)
        for value in (float("nan"), float("inf")):
            with pytest.raises(ValueError, match="finite and > 0"):
                store.renew(reserved.allocation_id, ttl_seconds=value, now=1.0)
            with pytest.raises(ValueError, match="observation time must be finite"):
                store.reconcile_orphans(now=value)


def test_workspace_and_recovery_keep_distinct_storage_mechanics_and_authorities() -> None:
    assert workspace_runtime_module.atomic_replace_bytes is platform_atomic_replace_bytes

    with TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = LocalWorkspaceManager(_DirectoryLayoutStub(root / "resource"))
        allocation = workspace.allocate_workspace(
            "workspace-a", scope=PLATFORM_SCOPE, category="proof", owner="role02"
        )
        recovery_db = root / "reliability" / "resource-authority.sqlite"
        recovery = recovery_lease_state(recovery_db)
        lease = recovery.acquire("recovery-owner", "manifest-digest", ttl_seconds=10.0, now=1.0)

        workspace_document = json.loads((allocation.path / ".workspace.json").read_text(encoding="utf-8"))
        with closing(sqlite3.connect(recovery_db)) as conn:
            resource_row = conn.execute(
                "SELECT resource_kind, resource_id FROM resource_owners WHERE resource_key=?",
                ("recovery:runtime",),
            ).fetchone()
            lease_row = conn.execute(
                "SELECT state, holder_generation, fencing_token FROM resource_leases WHERE resource_key=?",
                ("recovery:runtime",),
            ).fetchone()
        assert workspace_document["schema"] == "resource.workspace-allocation.v2"
        assert resource_row == ("recovery", "runtime")
        assert lease_row == ("active", 1, 1)
        assert workspace.list_workspaces(scope=PLATFORM_SCOPE, category="proof") == (allocation,)
        assert recovery.read() == lease
        assert allocation.workspace_id != lease.owner_id

def test_recovery_lease_rejects_non_finite_or_non_monotonic_timeline() -> None:
    with pytest.raises(ValueError, match="timestamps must be finite"):
        RecoveryLease("owner", "manifest", float("nan"), 2.0)
    with pytest.raises(ValueError, match="timestamps must be finite"):
        RecoveryLease("owner", "manifest", 1.0, float("inf"))
    with pytest.raises(ValueError, match="later than acquisition"):
        RecoveryLease("owner", "manifest", 2.0, 2.0)
    with pytest.raises(ValueError, match="owner and manifest identity"):
        RecoveryLease("", "manifest", 1.0, 2.0)


def test_recovery_store_and_execution_fence_reject_non_finite_ttl_and_clock() -> None:
    with TemporaryDirectory() as directory:
        store = recovery_lease_state(Path(directory) / "recovery-lease.json")
        for value in (float("nan"), float("inf")):
            with pytest.raises(ValueError, match="ttl_seconds must be finite"):
                store.acquire("owner", "manifest", ttl_seconds=value, now=1.0)
            with pytest.raises(ValueError, match="observation time must be finite"):
                store.acquire("owner", "manifest", ttl_seconds=10.0, now=value)
            with pytest.raises(ValueError, match="ttl_seconds must be finite"):
                FileLockedRecoveryExecutionFactory(
                    _LeaseStateStub(), lock_path=Path(directory) / "recovery.lock"
                ).execution("owner", "manifest", ttl_seconds=value)
