from __future__ import annotations

from contextlib import closing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event

import pytest

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocation,
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
    EndpointPhysicalConvergencePending,
    InMemoryEndpointAllocator,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
)
from noetrium_platform.infrastructure.resources.providers import SQLiteResourceLeaseRegistry
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
    ManualLeaseClock,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind


def _clock(
    *,
    elapsed: float = 1.0,
    wall: float = 100.0,
) -> ManualLeaseClock:
    return ManualLeaseClock(
        elapsed_seconds=elapsed,
        wall_epoch_seconds=wall,
    )


def _sqlite_endpoint_store(path, *, clock=None, **kwargs):
    return SQLiteEndpointAllocationStore(
        path,
        clock=_clock() if clock is None else clock,
        **kwargs,
    )


def _sqlite_resource_leases(path, *, clock=None, **kwargs):
    return SQLiteResourceLeaseRegistry(
        path,
        clock=_clock() if clock is None else clock,
        **kwargs,
    )


class _AvailableProbe:
    def __init__(self, barrier: Barrier | None = None) -> None:
        self._barrier = barrier

    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        if self._barrier is not None:
            self._barrier.wait(timeout=5)
        return EndpointProbeResult(endpoint, True, "available")


class _MutableProbe:
    def __init__(self) -> None:
        self.available = True
        self.unavailable_ports: set[int] = set()
        self.raise_error = False

    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        if self.raise_error:
            raise OSError("simulated endpoint observation failure")
        available = self.available and endpoint.port not in self.unavailable_ports
        return EndpointProbeResult(
            endpoint,
            available,
            "available" if available else "listener-still-present",
        )


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
            reservations=_sqlite_endpoint_store(database),
            probe=_AvailableProbe(barrier),
            lease_ttl_seconds=60,
        )
        right = AtomicEndpointAllocator(
            reservations=_sqlite_endpoint_store(database),
            probe=_AvailableProbe(barrier),
            lease_ttl_seconds=60,
        )
        request = _request("same")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda allocator: allocator.allocate(request), (left, right)))

        assert results[0] == results[1]
        assert len(_sqlite_endpoint_store(database).active()) == 1
        assert _active_lease_count(database) == 1


@pytest.mark.parametrize("durable", (False, True))
def test_expiry_quarantines_endpoint_until_os_listener_converges(
    tmp_path,
    durable: bool,
) -> None:
    probe = _MutableProbe()
    clock = _clock()
    if durable:
        allocator = AtomicEndpointAllocator(
            reservations=_sqlite_endpoint_store(
                tmp_path / "endpoint-quarantine.sqlite", clock=clock
            ),
            probe=probe,
            lease_ttl_seconds=0.05,
        )
    else:
        resources = InMemoryResourceLeaseRegistry(clock=clock)
        allocator = InMemoryEndpointAllocator(
            ownership=resources,
            leases=resources,
            probe=probe,
            lease_ttl_seconds=0.05,
        )

    first = allocator.allocate(_request("first"))
    first = allocator.confirm_bound(_binding_proof(first))
    expiry = first.lease_expires_at_epoch_s
    assert expiry is not None

    clock.advance(1.0)
    probe.unavailable_ports.add(first.endpoint.port)
    with pytest.raises(
        EndpointPhysicalConvergencePending,
        match="physical convergence is not proven",
    ):
        allocator.reconcile()

    current = allocator.get(first.allocation_id)
    assert current.state.is_live
    assert allocator.active() == (current,)

    # The stale generation quarantines only its own endpoint. It must not
    # freeze unrelated endpoint capacity needed by another model/environment.
    with pytest.raises(EndpointAllocationUnavailable, match="generation-quarantined"):
        allocator.allocate(_request("same-port", port=first.endpoint.port))
    replacement = allocator.allocate(_request("replacement", port=25566))
    assert replacement.endpoint.port == 25566

    probe.unavailable_ports.clear()
    retired = allocator.reconcile()
    assert len(retired) == 1
    assert retired[0].allocation_id == first.allocation_id
    assert retired[0].state is EndpointAllocationState.RELEASED

    reused = allocator.allocate(_request("reused", port=first.endpoint.port))
    assert reused.endpoint == first.endpoint
    assert reused.lease_fencing_token > first.lease_fencing_token


@pytest.mark.parametrize("durable", (False, True))
def test_endpoint_orphan_probe_failure_retains_quarantined_generation(
    tmp_path,
    durable: bool,
) -> None:
    probe = _MutableProbe()
    clock = _clock()
    if durable:
        allocator = AtomicEndpointAllocator(
            reservations=_sqlite_endpoint_store(
                tmp_path / "endpoint-probe-unknown.sqlite", clock=clock
            ),
            probe=probe,
            lease_ttl_seconds=0.05,
        )
    else:
        resources = InMemoryResourceLeaseRegistry(clock=clock)
        allocator = InMemoryEndpointAllocator(
            ownership=resources,
            leases=resources,
            probe=probe,
            lease_ttl_seconds=0.05,
        )

    first = allocator.allocate(_request("unknown"))
    first = allocator.confirm_bound(_binding_proof(first))
    expiry = first.lease_expires_at_epoch_s
    assert expiry is not None
    clock.advance(1.0)
    probe.raise_error = True

    with pytest.raises(OSError, match="observation failure"):
        allocator.reconcile()

    assert allocator.get(first.allocation_id).state.is_live
    assert tuple(row.allocation_id for row in allocator.active()) == ("unknown",)

    probe.raise_error = False
    assert allocator.reconcile()[0].allocation_id == "unknown"


@pytest.mark.parametrize("durable", (False, True))
def test_unbound_reservation_release_ignores_external_listener(
    tmp_path,
    durable: bool,
) -> None:
    probe = _MutableProbe()
    if durable:
        allocator = AtomicEndpointAllocator(
            reservations=_sqlite_endpoint_store(
                tmp_path / "endpoint-unbound-release.sqlite"
            ),
            probe=probe,
            lease_ttl_seconds=30.0,
        )
    else:
        resources = InMemoryResourceLeaseRegistry()
        allocator = InMemoryEndpointAllocator(
            ownership=resources,
            leases=resources,
            probe=probe,
            lease_ttl_seconds=30.0,
        )

    reserved = allocator.allocate(_request("unbound-release"))
    assert reserved.state is EndpointAllocationState.RESERVED
    probe.available = False

    released = allocator.release(reserved)
    assert released.state is EndpointAllocationState.RELEASED


@pytest.mark.parametrize("durable", (False, True))
def test_expired_unbound_reservation_retires_without_probe_authority(
    tmp_path,
    durable: bool,
) -> None:
    probe = _MutableProbe()
    clock = _clock()
    if durable:
        allocator = AtomicEndpointAllocator(
            reservations=_sqlite_endpoint_store(
                tmp_path / "endpoint-unbound-expiry.sqlite", clock=clock
            ),
            probe=probe,
            lease_ttl_seconds=0.05,
        )
    else:
        resources = InMemoryResourceLeaseRegistry(clock=clock)
        allocator = InMemoryEndpointAllocator(
            ownership=resources,
            leases=resources,
            probe=probe,
            lease_ttl_seconds=0.05,
        )

    reserved = allocator.allocate(_request("unbound-expiry"))
    expiry = reserved.lease_expires_at_epoch_s
    assert expiry is not None
    clock.advance(1.0)
    probe.raise_error = True

    retired = allocator.reconcile()
    assert tuple(row.allocation_id for row in retired) == ("unbound-expiry",)
    assert allocator.get("unbound-expiry").state is EndpointAllocationState.RELEASED


def test_renew_is_fenced_and_atomic_with_allocation_expiry_projection() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = _sqlite_endpoint_store(database)
        allocator = AtomicEndpointAllocator(
            reservations=store,
            probe=_AvailableProbe(),
            lease_ttl_seconds=30,
        )
        current = allocator.allocate(_request("renew"))
        renewed = allocator.renew(current, ttl_seconds=120)
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
        assert reconciled.state.is_live
        with pytest.raises(RuntimeError):
            allocator.renew(current, ttl_seconds=120)


def test_release_updates_lease_and_allocation_in_one_transaction() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = _sqlite_endpoint_store(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        allocation = allocator.allocate(_request("release"))

        released = allocator.release(allocation)
        assert released.state is EndpointAllocationState.RELEASED
        lease = _sqlite_resource_leases(database).get(allocation.lease_id)
        assert lease.state is LeaseState.RELEASED
        assert allocator.release(allocation) == released


def test_endpoint_lease_persists_canonical_acquire_and_release_provenance() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = _sqlite_endpoint_store(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        allocation = allocator.allocate(_request("provenance"))

        leases = _sqlite_resource_leases(database)
        acquired = leases.get(allocation.lease_id)
        assert acquired.acquired_at_epoch_s is not None
        assert acquired.released_at_epoch_s is None

        allocator.release(allocation)
        released = leases.get(allocation.lease_id)
        assert released.state is LeaseState.RELEASED
        assert released.released_at_epoch_s is not None
        assert released.released_at_epoch_s >= acquired.acquired_at_epoch_s


def test_endpoint_reconciliation_does_not_expire_other_resource_kinds() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        clock = _clock()
        leases = _sqlite_resource_leases(database, clock=clock)
        compute = ResourceIdentity(ResourceKind.COMPUTE, "host-scoped-reconcile")
        leases.register_owner(ResourceOwner(compute, PLATFORM_SCOPE))
        granted = leases.acquire(
            ResourceLease("compute-lease", compute, PLATFORM_SCOPE, "scope isolation"),
            ttl_seconds=1.0,
        )
        assert granted.state is LeaseState.ACTIVE

        clock.advance(2.0)
        endpoint_store = _sqlite_endpoint_store(database, clock=clock)
        assert endpoint_store.expire_orphans() == ()
        with closing(sqlite3.connect(database)) as conn:
            state = conn.execute(
                "SELECT state FROM resource_leases WHERE lease_id='compute-lease'"
            ).fetchone()
        assert state == ("active",)

        reconciled = leases.reconcile_expired()
        assert [row.lease_id for row in reconciled] == ["compute-lease"]


def test_early_external_lease_release_is_reconciled_by_point_get() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        store = _sqlite_endpoint_store(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_AvailableProbe())
        allocation = allocator.allocate(_request("orphan"))

        _sqlite_resource_leases(database).release(
            allocation.lease_id,
            fencing_token=allocation.lease_fencing_token,
        )
        current = store.get("orphan")
        assert current is not None
        assert current.state.is_live

        retired = allocator.reconcile()
        assert tuple(row.allocation_id for row in retired) == ("orphan",)
        assert store.get("orphan").state is EndpointAllocationState.RELEASED  # type: ignore[union-attr]


def test_concurrent_schema_bootstrap_is_idempotent() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        barrier = Barrier(8)

        def build(_: int) -> int:
            barrier.wait(timeout=5)
            _sqlite_endpoint_store(database)
            _sqlite_resource_leases(database)
            return 1

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(build, range(8))) == 8
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute(
                "SELECT value FROM endpoint_meta WHERE key='schema_version'"
            ).fetchone() == ("4",)
            assert conn.execute(
                "SELECT value FROM resource_meta WHERE key='schema_version'"
            ).fetchone() == (str(SQLiteResourceLeaseRegistry.SCHEMA_VERSION),)


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
        store = _sqlite_endpoint_store(database)
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

        released = allocator.release(reserved)
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
        _sqlite_endpoint_store(database)
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
        def renew_many(
            self,
            allocations: tuple[EndpointAllocation, ...],
            *,
            ttl_seconds: float | None = None,
        ):
            renewed.set()
            raise RuntimeError(
                f"renew failed: {allocations[0].allocation_id}:{ttl_seconds}"
            )

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
    ).create((
        EndpointAllocation(
            allocation_id="allocation-a",
            endpoint=NetworkEndpoint("127.0.0.1", 25565),
            lease_id="lease-a",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "branch-a"),
            purpose="heartbeat failure",
            request_digest="d" * 64,
            lease_expires_at_epoch_s=100.0,
        ),
    ))
    guard.start()
    assert renewed.wait(timeout=1.0)
    with pytest.raises(EndpointLeaseHeartbeatError, match="renew failed"):
        guard.assert_healthy()
    guard.close()
    heartbeat = runtime.topology_snapshot().heartbeats[0]
    assert heartbeat.active is False
    assert heartbeat.failure_type is not None
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
        store = _sqlite_endpoint_store(database)
        allocator = AtomicEndpointAllocator(reservations=store, probe=_RebindAvailableProbe())
        reserved = allocator.allocate(_rebind_request("sqlite", 25566))
        _assert_rebind_contract(allocator, reserved)
        reopened = _sqlite_endpoint_store(database).get(reserved.allocation_id)
        assert reopened is not None
        assert reopened.binding_binder_identity_digest == "b" * 64
        assert reopened.binding_evidence_ref == "ready:b"
        assert reopened.bound_at_epoch_s == 1001.0


def test_sqlite_concurrent_rebind_has_exactly_one_winner() -> None:
    with TemporaryDirectory() as directory:
        database = Path(directory) / "platform.sqlite"
        left = AtomicEndpointAllocator(
            reservations=_sqlite_endpoint_store(database), probe=_RebindAvailableProbe()
        )
        reserved = left.allocate(_rebind_request("sqlite-race", 25567))
        first = _rebind_proof(reserved, "a", 1000.0)
        left.confirm_bound(first)
        contenders = (_rebind_proof(reserved, "b", 1001.0), _rebind_proof(reserved, "c", 1002.0))

        def attempt(proof):
            allocator = AtomicEndpointAllocator(
                reservations=_sqlite_endpoint_store(database), probe=_RebindAvailableProbe()
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
        persisted = _sqlite_endpoint_store(database).get(reserved.allocation_id)
        assert persisted == winners[0]
        assert persisted is not None
        assert persisted.binding_binder_identity_digest in {"b" * 64, "c" * 64}


def test_binding_metadata_rejects_noncanonical_persisted_rebind_proof_digest() -> None:
    allocator, reserved = _rebind_in_memory("metadata")
    bound = allocator.confirm_bound(_rebind_proof(reserved, "a", 1000.0))
    with pytest.raises(ValueError, match="binding proof"):
        type(bound)(**{**{field: getattr(bound, field) for field in bound.__dataclass_fields__},
                       "binding_proof_digest": "not-a-digest"})



def test_released_endpoint_identity_remains_terminal_across_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "endpoint-terminal.sqlite"
    request = _request("terminal-endpoint", port=25601)
    first = AtomicEndpointAllocator(
        reservations=_sqlite_endpoint_store(database),
        probe=_AvailableProbe(),
    )
    allocation = first.allocate(request)
    released = first.release(allocation)
    assert released.state is EndpointAllocationState.RELEASED

    restarted = AtomicEndpointAllocator(
        reservations=_sqlite_endpoint_store(database),
        probe=_AvailableProbe(),
    )
    with pytest.raises(
        EndpointAllocationConflict,
        match="already released",
    ):
        restarted.allocate(request)
    assert restarted.get(allocation.allocation_id) == released
