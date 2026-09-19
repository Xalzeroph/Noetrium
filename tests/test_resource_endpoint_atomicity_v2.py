from __future__ import annotations

from contextlib import closing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event

import pytest

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocationRequest,
    EndpointLeasePolicy,
    EndpointAllocationState,
    EndpointBindingProof,
    EndpointProbeResult,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.providers import SQLiteEndpointAllocationStore
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.resources.allocation.runtime import (
    AtomicEndpointAllocator,
    EndpointLeaseHeartbeatError,
    EndpointLeaseHeartbeatFactory,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
)
from noetrium_platform.infrastructure.resources.providers import SQLiteResourceLeaseRegistry
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind


class _AvailableProbe:
    def __init__(self, barrier: Barrier | None = None) -> None:
        self._barrier = barrier

    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        if self._barrier is not None:
            self._barrier.wait(timeout=5)
        return EndpointProbeResult(endpoint, True, "available")


def _request(allocation_id: str, *, port: int = 25565) -> EndpointAllocationRequest:
    return EndpointAllocationRequest(
        allocation_id=allocation_id,
        holder_scope=ScopeIdentity(ScopeKind.BRANCH, f"branch-{allocation_id}"),
        purpose="atomic endpoint test",
        host="127.0.0.1",
        candidate_ports=(port,),
    )


def _active_lease_count(database: Path) -> int:
    with closing(sqlite3.connect(database)) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM resource_leases WHERE state='active'").fetchone()[0])


def test_same_allocation_race_commits_exactly_one_allocation_and_one_lease() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        barrier = Barrier(2)
        left = AtomicEndpointAllocator(
            reservations=SQLiteEndpointAllocationStore(database),
            probe=_AvailableProbe(barrier),
            lease_ttl_seconds=60,
        )
        right = AtomicEndpointAllocator(
            reservations=SQLiteEndpointAllocationStore(database),
            probe=_AvailableProbe(barrier),
            lease_ttl_seconds=60,
        )
        request = _request("same")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda allocator: allocator.allocate(request), (left, right)))

        assert results[0] == results[1]
        assert len(SQLiteEndpointAllocationStore(database).active()) == 1
        assert _active_lease_count(database) == 1


def test_expiry_releases_orphan_and_next_allocation_gets_higher_fencing_token() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = SQLiteEndpointAllocationStore(database)
        first_allocator = AtomicEndpointAllocator(
            reservations=store,
            probe=_AvailableProbe(),
            lease_ttl_seconds=0.05,
        )
        first = first_allocator.allocate(_request("first"))
        assert first.lease_fencing_token == 1

        expired = store.reconcile_orphans(now=(first.lease_expires_at_epoch_s or 0) + 1)
        assert [row.allocation_id for row in expired] == ["first"]
        assert store.get("first").state is EndpointAllocationState.RELEASED  # type: ignore[union-attr]

        second = AtomicEndpointAllocator(
            reservations=store,
            probe=_AvailableProbe(),
            lease_ttl_seconds=60,
        ).allocate(_request("second"))
        assert second.endpoint == first.endpoint
        assert second.lease_fencing_token > first.lease_fencing_token


def test_renew_is_fenced_and_atomic_with_allocation_expiry_projection() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = SQLiteEndpointAllocationStore(database)
        allocator = AtomicEndpointAllocator(
            reservations=store,
            probe=_AvailableProbe(),
            lease_ttl_seconds=30,
        )
        current = allocator.allocate(_request("renew"))
        renewed = allocator.renew("renew", ttl_seconds=120)
        assert renewed.lease_fencing_token == current.lease_fencing_token
        assert renewed.lease_expires_at_epoch_s is not None
        assert current.lease_expires_at_epoch_s is not None
        assert renewed.lease_expires_at_epoch_s > current.lease_expires_at_epoch_s

        # Simulate a stale external holder by replacing the lease fencing token.
        with closing(sqlite3.connect(database)) as conn:
            conn.execute(
                "UPDATE resource_leases SET fencing_token=fencing_token+1 WHERE lease_id=?",
                (current.lease_id,),
            )
            conn.commit()
        reconciled = store.get("renew")
        assert reconciled is not None
        assert reconciled.state is EndpointAllocationState.RELEASED
        with pytest.raises(RuntimeError):
            allocator.renew("renew", ttl_seconds=120)


def test_release_updates_lease_and_allocation_in_one_transaction() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = SQLiteEndpointAllocationStore(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        allocation = allocator.allocate(_request("release"))

        released = allocator.release("release")
        assert released.state is EndpointAllocationState.RELEASED
        lease = SQLiteResourceLeaseRegistry(database).get(allocation.lease_id)
        assert lease.state is LeaseState.RELEASED
        assert allocator.release("release") == released


def test_endpoint_lease_persists_canonical_acquire_and_release_provenance() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = SQLiteEndpointAllocationStore(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        allocation = allocator.allocate(_request("provenance"))

        leases = SQLiteResourceLeaseRegistry(database)
        acquired = leases.get(allocation.lease_id)
        assert acquired.acquired_at_epoch_s is not None
        assert acquired.released_at_epoch_s is None

        allocator.release(allocation.allocation_id)
        released = leases.get(allocation.lease_id)
        assert released.state is LeaseState.RELEASED
        assert released.released_at_epoch_s is not None
        assert released.released_at_epoch_s >= acquired.acquired_at_epoch_s


def test_endpoint_reconciliation_does_not_expire_other_resource_kinds() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        leases = SQLiteResourceLeaseRegistry(database)
        compute = ResourceIdentity(ResourceKind.COMPUTE, "host-scoped-reconcile")
        leases.register_owner(ResourceOwner(compute, PLATFORM_SCOPE))
        granted = leases.acquire(
            ResourceLease("compute-lease", compute, PLATFORM_SCOPE, "scope isolation"),
            ttl_seconds=1.0,
            now=10.0,
        )
        assert granted.state is LeaseState.ACTIVE

        endpoint_store = SQLiteEndpointAllocationStore(database)
        assert endpoint_store.reconcile_orphans(now=12.0) == ()
        with closing(sqlite3.connect(database)) as conn:
            state = conn.execute(
                "SELECT state FROM resource_leases WHERE lease_id='compute-lease'"
            ).fetchone()
        assert state == ("active",)

        reconciled = leases.reconcile_expired(now=12.0)
        assert [row.lease_id for row in reconciled] == ["compute-lease"]


def test_early_external_lease_release_is_reconciled_by_point_get() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = SQLiteEndpointAllocationStore(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        allocation = allocator.allocate(_request("orphan"))

        SQLiteResourceLeaseRegistry(database).release(allocation.lease_id)
        current = store.get("orphan")
        assert current is not None
        assert current.state is EndpointAllocationState.RELEASED


def test_concurrent_schema_bootstrap_is_idempotent() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        barrier = Barrier(8)

        def build(_: int) -> int:
            barrier.wait(timeout=5)
            SQLiteEndpointAllocationStore(database)
            SQLiteResourceLeaseRegistry(database)
            return 1

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(build, range(8))) == 8
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute(
                "SELECT value FROM endpoint_meta WHERE key='schema_version'"
            ).fetchone() == ("4",)
            assert conn.execute(
                "SELECT value FROM resource_meta WHERE key='schema_version'"
            ).fetchone() == ("4",)


def _binding_proof(allocation, *, evidence_ref: str = "runtime-listener-evidence:1") -> EndpointBindingProof:
    return EndpointBindingProof(
        allocation_id=allocation.allocation_id,
        endpoint=allocation.endpoint,
        lease_fencing_token=allocation.lease_fencing_token,
        binder_identity_digest="a" * 64,
        observed_at_epoch_s=1234.5,
        evidence_ref=evidence_ref,
    )


def test_endpoint_binding_requires_current_fencing_and_is_idempotent() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = SQLiteEndpointAllocationStore(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        reserved = allocator.allocate(_request("bind"))
        assert reserved.state is EndpointAllocationState.RESERVED
        assert reserved.binding_proof_digest is None

        proof = _binding_proof(reserved)
        bound = allocator.confirm_bound(proof)
        assert bound.state is EndpointAllocationState.BOUND
        assert bound.binding_proof_digest == proof.digest()
        assert bound.binding_evidence_ref == proof.evidence_ref
        assert allocator.confirm_bound(proof) == bound

        with pytest.raises(RuntimeError, match="different binding proof"):
            allocator.confirm_bound(_binding_proof(reserved, evidence_ref="runtime-listener-evidence:2"))
        stale = EndpointBindingProof(
            allocation_id=reserved.allocation_id,
            endpoint=reserved.endpoint,
            lease_fencing_token=reserved.lease_fencing_token + 1,
            binder_identity_digest="b" * 64,
            observed_at_epoch_s=1235.0,
            evidence_ref="stale-listener-evidence",
        )
        with pytest.raises(RuntimeError, match="fencing lost"):
            allocator.confirm_bound(stale)

        released = allocator.release(reserved.allocation_id)
        assert released.state is EndpointAllocationState.RELEASED
        assert released.binding_proof_digest == proof.digest()
        assert released.binding_evidence_ref == proof.evidence_ref


def test_v2_active_endpoint_migrates_fail_closed_to_reserved() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("CREATE TABLE endpoint_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO endpoint_meta VALUES('schema_version','2')")
            conn.execute(
                """
                CREATE TABLE endpoint_allocations(
                    allocation_id TEXT PRIMARY KEY, host TEXT NOT NULL, port INTEGER NOT NULL,
                    protocol TEXT NOT NULL, lease_id TEXT NOT NULL, holder_scope_kind TEXT NOT NULL,
                    holder_scope_id TEXT NOT NULL, purpose TEXT NOT NULL, request_digest TEXT NOT NULL,
                    state TEXT NOT NULL, lease_holder_generation INTEGER NOT NULL DEFAULT 1,
                    lease_fencing_token INTEGER NOT NULL DEFAULT 1, lease_expires_at_epoch_s REAL
                )
                """
            )
            conn.execute(
                "INSERT INTO endpoint_allocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "legacy", "127.0.0.1", 25565, "tcp", "legacy-lease", "branch", "legacy",
                    "legacy endpoint", "d" * 64, "active", 1, 7, 9999999999.0,
                ),
            )
            conn.commit()
        SQLiteEndpointAllocationStore(database)
        with closing(sqlite3.connect(database)) as conn:
            row = conn.execute(
                "SELECT state,binding_proof_digest,binding_evidence_ref,bound_at_epoch_s "
                "FROM endpoint_allocations WHERE allocation_id='legacy'"
            ).fetchone()
            version = conn.execute(
                "SELECT value FROM endpoint_meta WHERE key='schema_version'"
            ).fetchone()
        assert row == ("reserved", None, None, None)
        assert version == ("4",)


def test_endpoint_heartbeat_surfaces_background_renewal_failure() -> None:
    renewed = Event()

    class _FailingAllocations:
        def renew_many(self, allocation_ids: tuple[str, ...], *, ttl_seconds: float | None = None):
            renewed.set()
            raise RuntimeError(f"renew failed: {allocation_ids[0]}:{ttl_seconds}")

    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=8,
        ),
        blocking_io_thread_name_prefix="atomic-heartbeat-failure-io",
        timer_name="atomic-heartbeat-failure-timer",
    )
    group = runtime.open_task_group("atomic-heartbeat-failure")
    guard = EndpointLeaseHeartbeatFactory(
        allocations=_FailingAllocations(),  # type: ignore[arg-type]
        task_group=group,
        heartbeat_scheduler=runtime.heartbeats,
        lane_id="atomic-heartbeat-failure-writer",
        lane_capacity=8,
        policy=EndpointLeasePolicy(ttl_seconds=0.2, renewal_interval_seconds=0.01),
    ).create(("allocation-a",))
    guard.start()
    assert renewed.wait(timeout=1.0)
    with pytest.raises(EndpointLeaseHeartbeatError, match="renew failed"):
        guard.assert_healthy()
    with pytest.raises(EndpointLeaseHeartbeatError, match="renew failed"):
        guard.close()
    with pytest.raises(ExceptionGroup):
        runtime.close()


# Endpoint BOUND-generation replacement supervisor regressions
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocationRequest,
    EndpointBindingProof,
    EndpointProbeResult,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import (
    AtomicEndpointAllocator,
    EndpointAllocationConflict,
    InMemoryEndpointAllocator,
)
from noetrium_platform.infrastructure.resources.lease.runtime import InMemoryResourceLeaseRegistry
from noetrium_platform.infrastructure.resources.providers import SQLiteEndpointAllocationStore
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


class _RebindAvailableProbe:
    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        return EndpointProbeResult(endpoint, True, "available")


def _rebind_request(name: str, port: int = 25565) -> EndpointAllocationRequest:
    return EndpointAllocationRequest(
        allocation_id=name,
        holder_scope=ScopeIdentity(ScopeKind.BRANCH, f"branch-{name}"),
        purpose="endpoint rebind test",
        host="127.0.0.1",
        candidate_ports=(port,),
    )


def _rebind_proof(allocation, generation: str, observed: float) -> EndpointBindingProof:
    return EndpointBindingProof(
        allocation_id=allocation.allocation_id,
        endpoint=allocation.endpoint,
        lease_fencing_token=allocation.lease_fencing_token,
        binder_identity_digest=generation * 64,
        observed_at_epoch_s=observed,
        evidence_ref=f"ready:{generation}",
    )


def _rebind_in_memory(name: str = "mem"):
    leases = InMemoryResourceLeaseRegistry()
    allocator = InMemoryEndpointAllocator(
        ownership=leases, leases=leases, probe=_RebindAvailableProbe()
    )
    return allocator, allocator.allocate(_rebind_request(name))


def _assert_rebind_contract(allocator, reserved) -> None:
    first = _rebind_proof(reserved, "a", 1000.0)
    bound = allocator.confirm_bound(first)
    assert bound.binding_binder_identity_digest == first.binder_identity_digest
    assert allocator.confirm_bound(first) == bound
    second = _rebind_proof(bound, "b", 1001.0)
    rebound = allocator.replace_bound(
        second, expected_previous_binding_proof_digest=first.digest()
    )
    assert rebound.binding_proof_digest == second.digest()
    assert rebound.binding_binder_identity_digest == second.binder_identity_digest
    assert rebound.bound_at_epoch_s == second.observed_at_epoch_s


def test_rebind_in_memory_bound_generation_replacement_is_cas_fenced() -> None:
    allocator, reserved = _rebind_in_memory()
    _assert_rebind_contract(allocator, reserved)


def test_rebind_in_memory_rebind_rejects_stale_prior_same_binder_and_stale_fence() -> None:
    allocator, reserved = _rebind_in_memory("negatives")
    first = _rebind_proof(reserved, "a", 1000.0)
    bound = allocator.confirm_bound(first)
    same_binder = _rebind_proof(bound, "a", 1001.0)
    with pytest.raises(EndpointAllocationConflict, match="new binder generation"):
        allocator.replace_bound(
            same_binder, expected_previous_binding_proof_digest=first.digest()
        )
    second = _rebind_proof(bound, "b", 1002.0)
    with pytest.raises(EndpointAllocationConflict, match="prior generation"):
        allocator.replace_bound(second, expected_previous_binding_proof_digest="f" * 64)
    stale = EndpointBindingProof(
        bound.allocation_id, bound.endpoint, bound.lease_fencing_token + 1,
        "c" * 64, 1003.0, "ready:c",
    )
    with pytest.raises(EndpointAllocationConflict, match="fencing lost"):
        allocator.replace_bound(stale, expected_previous_binding_proof_digest=first.digest())
    assert allocator.get(bound.allocation_id) == bound


def test_rebind_in_memory_concurrent_rebind_has_exactly_one_winner() -> None:
    allocator, reserved = _rebind_in_memory("race")
    first = _rebind_proof(reserved, "a", 1000.0)
    allocator.confirm_bound(first)
    contenders = (_rebind_proof(reserved, "b", 1001.0), _rebind_proof(reserved, "c", 1002.0))

    def attempt(proof):
        try:
            return allocator.replace_bound(
                proof, expected_previous_binding_proof_digest=first.digest()
            )
        except EndpointAllocationConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(attempt, contenders))
    winners = tuple(row for row in results if row is not None)
    assert len(winners) == 1
    assert allocator.get(reserved.allocation_id) == winners[0]
    with pytest.raises(EndpointAllocationConflict, match="prior generation"):
        allocator.replace_bound(
            _rebind_proof(reserved, "d", 1003.0),
            expected_previous_binding_proof_digest=first.digest(),
        )


def test_sqlite_rebind_persists_winning_generation_across_reopen() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = SQLiteEndpointAllocationStore(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_RebindAvailableProbe())
        reserved = allocator.allocate(_rebind_request("sqlite", 25566))
        _assert_rebind_contract(allocator, reserved)
        reopened = SQLiteEndpointAllocationStore(database).get(reserved.allocation_id)
        assert reopened is not None
        assert reopened.binding_binder_identity_digest == "b" * 64
        assert reopened.binding_evidence_ref == "ready:b"
        assert reopened.bound_at_epoch_s == 1001.0


def test_sqlite_concurrent_rebind_has_exactly_one_winner() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        left = AtomicEndpointAllocator(
            reservations=SQLiteEndpointAllocationStore(database), probe=_RebindAvailableProbe()
        )
        reserved = left.allocate(_rebind_request("sqlite-race", 25567))
        first = _rebind_proof(reserved, "a", 1000.0)
        left.confirm_bound(first)
        contenders = (_rebind_proof(reserved, "b", 1001.0), _rebind_proof(reserved, "c", 1002.0))

        def attempt(proof):
            allocator = AtomicEndpointAllocator(
                reservations=SQLiteEndpointAllocationStore(database), probe=_RebindAvailableProbe()
            )
            try:
                return allocator.replace_bound(
                    proof, expected_previous_binding_proof_digest=first.digest()
                )
            except RuntimeError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(attempt, contenders))
        winners = tuple(row for row in results if row is not None)
        assert len(winners) == 1
        persisted = SQLiteEndpointAllocationStore(database).get(reserved.allocation_id)
        assert persisted == winners[0]
        assert persisted is not None
        assert persisted.binding_binder_identity_digest in {"b" * 64, "c" * 64}


def test_binding_metadata_rejects_noncanonical_persisted_rebind_proof_digest() -> None:
    allocator, reserved = _rebind_in_memory("metadata")
    bound = allocator.confirm_bound(_rebind_proof(reserved, "a", 1000.0))
    with pytest.raises(ValueError, match="binding proof"):
        type(bound)(**{**{field: getattr(bound, field) for field in bound.__dataclass_fields__},
                       "binding_proof_digest": "not-a-digest"})
