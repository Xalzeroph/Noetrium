from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
import time

import pytest

from noetrium_platform.infrastructure.resources.api.topology import (
    resource_node,
    resource_topology,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import (
    AuthoritySnapshot,
    ClaimAggregate,
    ReconcileActionKind,
    ResourceCapacity,
    ResourceClaimConflict,
    ResourceObservationNotReady,
    ResourceRealizationSpec,
    ResourceReconciliationPlanner,
    TicketState,
    UniversalResourceAuthority,
    authority_lease,
    binding_field,
    claim_field,
    compose_claims,
    is_realization_ticket,
    lease_field,
    lease_live_at,
    observation_field,
    physical_field,
    physical_identity,
    realization_binding,
    realization_ticket,
    resource_claim,
    resource_observation,
    resource_truth_modality,
    ticket_field,
)


def _platform_claim(
    claim_id: str,
    resource_key: str,
    holder_key: str,
    generation: int,
    amounts: tuple[tuple[str, int], ...] = (),
    shared: tuple[str, ...] = (),
    exclusive: tuple[str, ...] = (),
    *,
    attributes=None,
    owner_lease_id: str | None = None,
) -> NoetriumUnit:
    return resource_claim(
        claim_id,
        resource_key,
        holder_key,
        generation,
        owner_scope=PLATFORM_SCOPE,
        scope_generation=1,
        scope_lease_id=None,
        owner_lease_id=owner_lease_id,
        amounts=amounts,
        shared=shared,
        exclusive=exclusive,
        attributes=attributes,
    )


def _claim(
    claim_id: str,
    resource_key: str,
    *,
    generation: int = 1,
    amount: int = 0,
    exclusive: tuple[str, ...] = (),
) -> NoetriumUnit:
    return _platform_claim(
        claim_id,
        resource_key,
        "holder",
        generation,
        () if amount == 0 else (("cpu", amount),),
        (),
        exclusive,
    )


def _platform_lease(
    lease_id: str,
    resource_key: str,
    holder_key: str,
    generation: int,
    expires_at_epoch_s: float | None = None,
    released: bool = False,
    *,
    acquired_at_epoch_s: float | None = None,
    metadata=None,
) -> NoetriumUnit:
    return authority_lease(
        lease_id,
        resource_key,
        holder_key,
        generation,
        owner_scope=PLATFORM_SCOPE,
        scope_generation=1,
        scope_lease_id=None,
        expires_at_epoch_s=expires_at_epoch_s,
        released=released,
        acquired_at_epoch_s=acquired_at_epoch_s,
        metadata=metadata,
    )


def test_claim_algebra_is_commutative_and_associative_when_defined() -> None:
    cap = ResourceCapacity((("cpu", 100),))
    a = ClaimAggregate((("cpu", 10),), (), ("a",))
    b = ClaimAggregate((("cpu", 20),), (), ("b",))
    c = ClaimAggregate((("cpu", 30),), (), ("c",))
    assert a.compose(b, capacity=cap) == b.compose(a, capacity=cap)
    assert a.compose(b, capacity=cap).compose(c, capacity=cap) == a.compose(
        b.compose(c, capacity=cap),
        capacity=cap,
    )


def test_claim_algebra_fails_closed_on_capacity_and_exclusive_conflicts() -> None:
    cap = ResourceCapacity((("cpu", 4),))
    with pytest.raises(ResourceClaimConflict, match="capacity exceeded"):
        compose_claims(
            (
                _claim("a", "ra", amount=3),
                _claim("b", "rb", amount=2),
            ),
            capacity=cap,
        )
    with pytest.raises(ResourceClaimConflict, match="exclusive claim conflict"):
        compose_claims(
            (
                _claim("a", "ra", exclusive=("tcp:8000",)),
                _claim("b", "rb", exclusive=("tcp:8000",)),
            ),
            capacity=cap,
        )
    with pytest.raises(ResourceClaimConflict, match="undeclared"):
        compose_claims(
            (_platform_claim("x", "rx", "holder", 1, (("vram", 1),), (), ()),),
            capacity=cap,
        )


def test_resource_generation_fences_lease_liveness() -> None:
    lease = _platform_lease("l", "r", "holder", 1, 100.0, False)
    assert lease_live_at(lease, 10.0, current_generation=1)
    assert not lease_live_at(lease, 10.0, current_generation=2)


def _acquire_platform_ttl(authority, **kwargs):
    return authority.acquire_ttl_lease(
        owner_scope=PLATFORM_SCOPE,
        **kwargs,
    )


def _acquire_platform_exclusive_ttl(authority, **kwargs):
    return authority.acquire_exclusive_ttl_lease(
        owner_scope=PLATFORM_SCOPE,
        **kwargs,
    )


def test_single_flight_has_exactly_one_producer(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    generation = authority.ensure_generation("service")
    authority.acquire_claim(_claim("service-claim", "service"))

    def prepare(_: int) -> bool:
        _, producer = authority.prepare_realization(
            realization_key="same-realization",
            resource_key="service",
            generation=generation.generation,
            spec=ResourceRealizationSpec("test", {"name": "spec"}),
            holder_key="holder",
        )
        return producer

    with ThreadPoolExecutor(max_workers=8) as pool:
        producers = tuple(pool.map(prepare, range(32)))
    assert sum(producers) == 1


class _TicketProvider:
    def __init__(self) -> None:
        self.by_ticket: dict[str, NoetriumUnit] = {}
        self.ticket_by_physical: dict[str, NoetriumUnit] = {}

    def realize(self, _spec, ticket: NoetriumUnit) -> NoetriumUnit:
        identity = self.by_ticket.setdefault(
            ticket_field(ticket, "ticket_id"),
            physical_identity("fake", f"physical:{ticket_field(ticket, "effect_id")}"),
        )
        self.ticket_by_physical[identity.unit_digest] = ticket
        return identity

    def observe(
        self,
        reference: NoetriumUnit,
    ) -> NoetriumUnit:
        ticket = (
            reference
            if is_realization_ticket(reference)
            else self.ticket_by_physical.get(reference.unit_digest)
        )
        if ticket is None:
            raise TypeError("test provider requires ticket or known physical identity")
        identity = self.by_ticket.get(ticket_field(ticket, "ticket_id"))
        return resource_observation(
            ticket_field(ticket, "resource_key"),
            ticket_field(ticket, "generation"),
            ticket_field(ticket, "ticket_id"),
            ticket_field(ticket, "spec_digest"),
            identity is not None,
            identity is not None,
            identity,
        )

    def retire(
        self,
        reference: NoetriumUnit,
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        self.by_ticket.pop(ticket_field(ticket, "ticket_id"), None)
        return resource_observation(
            ticket_field(ticket, "resource_key"),
            ticket_field(ticket, "generation"),
            ticket_field(ticket, "ticket_id"),
            ticket_field(ticket, "spec_digest"),
            False,
            False,
            None,
        )


def test_crash_after_realize_before_binding_recovers_by_ticket(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite"
    authority = UniversalResourceAuthority(path)
    generation = authority.ensure_generation("service")
    authority.acquire_claim(_claim("claim", "service"))
    ticket, producer = authority.prepare_realization(
        realization_key="service-realization",
        resource_key="service",
        generation=generation.generation,
        spec=ResourceRealizationSpec("fake", {"name": "spec"}),
        holder_key="holder",
    )
    assert producer
    provider = _TicketProvider()
    identity = provider.realize({}, ticket)

    # Simulate process death before Authority.bind().
    recovered_authority = UniversalResourceAuthority(path)
    recovered_ticket = recovered_authority.snapshot().current_ticket_for("service")
    assert recovered_ticket == ticket
    observation = provider.observe(recovered_ticket)
    binding = recovered_authority.bind(ticket_field(ticket, "ticket_id"), observation)
    assert binding_field(binding, "physical_identity") == identity


def test_retire_then_reacquire_uses_fresh_resource_generation(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    topology = resource_topology(
        "fresh-generation",
        resources=(
            resource_node(
                "endpoint", kind="network-endpoint", authority_key="endpoint"
            ),
        ),
        requires=(),
    )

    def candidates(_snapshot, generation: int):
        return (_claim(f"endpoint-claim-{generation}", "endpoint", generation=generation),)

    first = authority.reconcile(
        topology,
        claim_candidates={"endpoint": candidates},
        realization_specs={},
        providers={},
    )
    first_generation = first.generation_for("endpoint")
    assert first_generation is not None

    retired = authority.reconcile(
        topology,
        claim_candidates={},
        realization_specs={},
        providers={},
        desired_resource_ids=frozenset(),
    )
    retired_generation = retired.generation_for("endpoint")
    assert retired_generation is not None
    assert retired_generation.generation > first_generation.generation

    recovered = authority.reconcile(
        topology,
        claim_candidates={"endpoint": candidates},
        realization_specs={},
        providers={},
    )
    recovered_generation = recovered.generation_for("endpoint")
    assert recovered_generation == retired_generation
    claims = recovered.current_claims_for("endpoint")
    assert len(claims) == 1
    assert claim_field(claims[0], "generation") == recovered_generation.generation


def test_non_ready_observation_is_typed_before_binding(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    generation = authority.ensure_generation("service")
    authority.acquire_claim(_claim("claim", "service", generation=generation.generation))
    ticket, _ = authority.prepare_realization(
        realization_key="r-not-ready",
        resource_key="service",
        generation=generation.generation,
        spec=ResourceRealizationSpec("fake", {"name": "spec"}),
        holder_key="holder",
    )
    observation = resource_observation(
        "service",
        generation.generation,
        ticket_field(ticket, "ticket_id"),
        ticket_field(ticket, "spec_digest"),
        True,
        False,
        physical_identity("fake", "physical-not-ready"),
    )
    with pytest.raises(ResourceObservationNotReady, match="only ready existing"):
        authority.bind(ticket_field(ticket, "ticket_id"), observation)


def test_stale_observation_cannot_authorize_new_generation(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    first = authority.ensure_generation("service")
    authority.acquire_claim(_claim("old-claim", "service"))
    ticket, _ = authority.prepare_realization(
        realization_key="r1",
        resource_key="service",
        generation=first.generation,
        spec=ResourceRealizationSpec("fake", {"name": "spec"}),
        holder_key="holder",
    )
    old_observation = resource_observation(
        "service",
        first.generation,
        ticket_field(ticket, "ticket_id"),
        ticket_field(ticket, "spec_digest"),
        True,
        True,
        physical_identity("fake", "old"),
    )
    authority.advance_generation("service")
    with pytest.raises(RuntimeError, match="generation is fenced"):
        authority.bind(ticket_field(ticket, "ticket_id"), old_observation)


def _topology():
    return resource_topology(
        "topology",
        resources=(
            resource_node("compute", kind="compute", authority_key="compute"),
            resource_node("endpoint", kind="network-endpoint", authority_key="endpoint"),
            resource_node(
                "service",
                kind="service",
                authority_key="service",
                realization=True,
            ),
        ),
        requires=(("endpoint", "compute"), ("service", "endpoint")),
    )


def test_reconciliation_retirement_precedes_capacity_release() -> None:
    ticket = realization_ticket(
        "ticket",
        "effect",
        "realization",
        "service",
        "fake",
        1,
        "spec",
        "holder",
        TicketState.BOUND,
    )
    snapshot = AuthoritySnapshot(
        generations=(),
        claims=(
            _claim("compute-claim", "compute"),
            _claim("endpoint-claim", "endpoint"),
            _claim("service-claim", "service"),
        ),
        leases=(),
        tickets=(ticket,),
        bindings=(
            realization_binding(
                "service",
                1,
                "ticket",
                "spec",
                physical_identity("fake", "physical"),
            ),
        ),
    )
    planner = ResourceReconciliationPlanner(_topology())
    plan = planner.plan(
        snapshot,
        {
            "service": resource_observation(
                "service",
                1,
                "ticket",
                "spec",
                True,
                True,
                physical_identity("fake", "physical"),
            )
        },
        desired_resource_ids=frozenset(),
    )
    kinds = [(row.kind, row.resource_id) for row in plan.actions]
    retire_index = kinds.index((ReconcileActionKind.RETIRE, "service"))
    endpoint_release = kinds.index(
        (ReconcileActionKind.RELEASE_CLAIM, "endpoint")
    )
    compute_release = kinds.index(
        (ReconcileActionKind.RELEASE_CLAIM, "compute")
    )
    assert retire_index < endpoint_release < compute_release


def test_reconciliation_is_idempotent_when_converged() -> None:
    generations = tuple()
    # Build an exact converged snapshot manually with current generations.
    from noetrium_platform.infrastructure.resources.authority import AuthorityGeneration

    generations = (
        AuthorityGeneration("compute", 1),
        AuthorityGeneration("endpoint", 1),
        AuthorityGeneration("service", 1),
    )
    ticket = realization_ticket(
        "ticket",
        "effect",
        "realization",
        "service",
        "fake",
        1,
        "spec",
        "holder",
        TicketState.BOUND,
    )
    identity = physical_identity("fake", "physical")
    snapshot = AuthoritySnapshot(
        generations=generations,
        claims=(
            _claim("compute-claim", "compute"),
            _claim("endpoint-claim", "endpoint"),
            _claim("service-claim", "service"),
        ),
        leases=(),
        tickets=(ticket,),
        bindings=(realization_binding("service", 1, "ticket", "spec", identity),),
    )
    observation = resource_observation(
        "service",
        1,
        "ticket",
        "spec",
        True,
        True,
        identity,
    )
    plan = ResourceReconciliationPlanner(_topology()).plan(
        snapshot,
        {"service": observation},
    )
    assert plan.converged


def test_prepared_ticket_with_observed_effect_binds_without_rebuild() -> None:
    from noetrium_platform.infrastructure.resources.authority import AuthorityGeneration

    ticket = realization_ticket(
        "ticket",
        "effect",
        "realization",
        "service",
        "fake",
        1,
        "spec",
        "holder",
        TicketState.PREPARED,
    )
    snapshot = AuthoritySnapshot(
        generations=(
            AuthorityGeneration("compute", 1),
            AuthorityGeneration("endpoint", 1),
            AuthorityGeneration("service", 1),
        ),
        claims=(
            _claim("compute-claim", "compute"),
            _claim("endpoint-claim", "endpoint"),
            _claim("service-claim", "service"),
        ),
        leases=(),
        tickets=(ticket,),
        bindings=(),
    )
    observation = resource_observation(
        "service",
        1,
        "ticket",
        "spec",
        True,
        True,
        physical_identity("fake", "physical"),
    )
    plan = ResourceReconciliationPlanner(_topology()).plan(
        snapshot,
        {"service": observation},
    )
    service_actions = [
        row.kind for row in plan.actions if row.resource_id == "service"
    ]
    assert service_actions == [ReconcileActionKind.BIND]


def test_cross_connection_exclusive_claim_has_one_linearizable_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authority.sqlite"
    left = UniversalResourceAuthority(path)
    right = UniversalResourceAuthority(path)
    left_generation = left.ensure_generation("endpoint:left")
    right_generation = right.ensure_generation("endpoint:right")
    token = "tcp:127.0.0.1:32123"
    claims = (
        _platform_claim(
            "left",
            "endpoint:left",
            "left-holder",
            left_generation.generation,
            exclusive=(token,),
        ),
        _platform_claim(
            "right",
            "endpoint:right",
            "right-holder",
            right_generation.generation,
            exclusive=(token,),
        ),
    )

    def admit(row: tuple[UniversalResourceAuthority, NoetriumUnit]) -> str:
        authority, claim = row
        try:
            return claim_field(authority.admit_first((claim,)), "claim_id")
        except ResourceClaimConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(admit, ((left, claims[0]), (right, claims[1]))))
    assert outcomes.count("conflict") == 1
    assert len(tuple(row for row in outcomes if row != "conflict")) == 1
    snapshot = left.snapshot()
    active = tuple(row for row in snapshot.claims if token in claim_field(row, "exclusive"))
    assert len(active) == 1


def test_old_generation_claim_release_ignores_current_generation_ticket(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    first = authority.ensure_generation("service")
    old_claim = _platform_claim(
        "old-claim",
        "service",
        "holder",
        first.generation,
    )
    authority.acquire_claim(old_claim)
    old_ticket, _ = authority.prepare_realization(
        realization_key="old",
        resource_key="service",
        generation=first.generation,
        spec=ResourceRealizationSpec("fake", {"name": "old-spec"}),
        holder_key="holder",
    )
    old_identity = physical_identity("fake", "old-physical")
    authority.bind(
        ticket_field(old_ticket, "ticket_id"),
        resource_observation(
            "service",
            first.generation,
            ticket_field(old_ticket, "ticket_id"),
            ticket_field(old_ticket, "spec_digest"),
            True,
            True,
            old_identity,
        ),
    )

    second = authority.advance_generation("service")
    authority.begin_retire(ticket_field(old_ticket, "ticket_id"))
    authority.complete_retire(
        ticket_field(old_ticket, "ticket_id"),
        resource_observation(
            "service",
            first.generation,
            ticket_field(old_ticket, "ticket_id"),
            ticket_field(old_ticket, "spec_digest"),
            False,
            False,
            None,
        ),
    )
    new_claim = _platform_claim(
        "new-claim",
        "service",
        "holder",
        second.generation,
    )
    authority.acquire_claim(new_claim)
    new_ticket, _ = authority.prepare_realization(
        realization_key="new",
        resource_key="service",
        generation=second.generation,
        spec=ResourceRealizationSpec("fake", {"name": "new-spec"}),
        holder_key="holder",
    )
    assert ticket_field(new_ticket, "state") is TicketState.PREPARED

    # The live current-generation ticket must not pin already-retired physical
    # occupancy from an older generation.
    released_old = authority.release_claim(claim_field(old_claim, "claim_id"))
    assert claim_field(released_old, "claim_id") == claim_field(old_claim, "claim_id")
    assert resource_truth_modality(released_old) is TruthModality.AUTHORIZED
    active_ids = {claim_field(row, "claim_id") for row in authority.snapshot().claims}
    assert active_ids == {claim_field(new_claim, "claim_id")}


def test_retirement_gate_atomically_blocks_new_consumer_leases(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    first = _acquire_platform_ttl(authority,
        lease_id="consumer-1",
        resource_key="runtime-fabric",
        holder_key="holder-1",
        ttl_seconds=60.0,
        now=10.0,
    )
    with pytest.raises(RuntimeError, match="live consumers"):
        authority.fence_if_no_live_leases(
            "runtime-fabric",
            holder_key="retirement",
            now=11.0,
        )
    authority.release_lease(first)
    gate = authority.fence_if_no_live_leases(
        "runtime-fabric",
        holder_key="retirement",
        now=12.0,
    )
    assert "lease-admission:runtime-fabric" in claim_field(gate, "exclusive")
    with pytest.raises(RuntimeError, match="admission is fenced"):
        _acquire_platform_ttl(authority,
            lease_id="consumer-2",
            resource_key="runtime-fabric",
            holder_key="holder-2",
            ttl_seconds=60.0,
            now=13.0,
        )


def test_compute_placement_is_pure_claim_projection() -> None:
    from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
    from noetrium_platform.infrastructure.resources.compute.api import (
        ComputeHost,
        ComputeRequirement,
    )
    from noetrium_platform.infrastructure.resources.compute.placement import (
        compute_capacity,
        compute_claim_candidates,
        compute_placement_from_claim,
    )

    host = ComputeHost(
        "host-a",
        PLATFORM_SCOPE,
        cpu_cores=8,
        memory_bytes=16 * 1024,
    )
    snapshot = AuthoritySnapshot((), (), (), (), ())
    candidates = compute_claim_candidates(
        resource_key="compute:trial-a",
        holder_key="trial-a",
        generation=1,
        consumer_resource_key="service:trial-a",
        requirement=ComputeRequirement(cpu_cores=2, memory_bytes=1024),
        hosts=(host,),
        authority=snapshot,
        placement_scope=PLATFORM_SCOPE,
        owner_scope=PLATFORM_SCOPE,
        scope_generation=1,
        scope_lease_id=None,
    )
    assert len(candidates) == 1
    claim = candidates[0]
    amounts = dict(claim_field(claim, "amounts"))
    assert amounts["compute:host-a:cpu-cores"] == 2
    assert amounts["compute:host-a:memory-bytes"] == 1024
    placement = compute_placement_from_claim(claim)
    assert placement.host_id == "host-a"
    assert placement.cpu_cores == 2
    assert placement.memory_bytes == 1024
    assert placement.resource_key == "compute:trial-a"
    capacity = dict(compute_capacity((host,)).by_dimension)
    assert capacity == {
        "compute:host-a:cpu-cores": 8,
        "compute:host-a:memory-bytes": 16 * 1024,
    }


def test_compute_placement_failure_preserves_observed_capacity_diagnostics() -> None:
    from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
    from noetrium_platform.infrastructure.resources.compute.api import (
        ComputeGPU,
        ComputeHost,
        ComputePlacementUnavailable,
        ComputeRequirement,
        GpuDeviceStatus,
        GpuRuntimeSnapshot,
        GpuSharingMode,
    )
    from noetrium_platform.infrastructure.resources.compute.placement import (
        compute_claim_candidates,
    )

    gpu_id = "GPU-test"
    host = ComputeHost(
        "host-a",
        PLATFORM_SCOPE,
        cpu_cores=8,
        memory_bytes=16 * 1024**3,
        gpus=(ComputeGPU(gpu_id, 16 * 1024**3),),
    )
    runtime = GpuRuntimeSnapshot(
        True,
        devices=(
            GpuDeviceStatus(
                "0",
                gpu_id,
                "test",
                16 * 1024,
                12 * 1024,
                4 * 1024,
                7,
            ),
        ),
    )
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=1024**3,
        gpu_count=1,
        required_gpu_free_memory_bytes=8 * 1024**3,
        gpu_admission_headroom_fraction=0.05,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    with pytest.raises(ComputePlacementUnavailable) as raised:
        compute_claim_candidates(
            resource_key="compute:diagnostic",
            holder_key="diagnostic",
            generation=1,
            consumer_resource_key="service:diagnostic",
            requirement=requirement,
            hosts=(host,),
            authority=AuthoritySnapshot((), (), (), (), ()),
            placement_scope=PLATFORM_SCOPE,
            owner_scope=PLATFORM_SCOPE,
            scope_generation=1,
            scope_lease_id=None,
            gpu_runtime=runtime,
        )
    diagnostics = raised.value.diagnostics
    assert diagnostics["eligible_host_count"] == 1
    gpu = diagnostics["hosts"][0]["gpus"][0]
    assert gpu["runtime_free_bytes"] == 4 * 1024**3
    assert gpu["required_admission_free_bytes"] > 8 * 1024**3
    assert gpu["memory_admissible"] is False


def test_endpoint_placement_width_is_derived_from_logical_contention() -> None:
    from noetrium_platform.infrastructure.resources.allocation.api import (
        EndpointProbeResult,
        NetworkEndpoint,
    )
    from noetrium_platform.infrastructure.resources.allocation.placement import (
        automatic_endpoint_claim_candidates,
        endpoint_placement_from_claim,
    )

    class Candidates:
        def __init__(self) -> None:
            self.requested = None

        def candidate_ports(self, *, host, count, protocol):
            self.requested = (host, count, protocol)
            return tuple(range(8100, 8100 + count))

    class Probe:
        def probe(self, endpoint):
            return EndpointProbeResult(endpoint, True, "free")

    existing = _platform_claim(
        "existing-endpoint",
        "endpoint:old",
        "old-holder",
        1,
        exclusive=(NetworkEndpoint("127.0.0.1", 8000).key,),
        attributes={
            "kind": "network-endpoint",
            "allocation_id": "old",
            "purpose": "old",
            "host": "127.0.0.1",
            "port": 8000,
            "protocol": "tcp",
            "consumer_resource_key": "service:old",
        },
    )
    snapshot = AuthoritySnapshot((), (existing,), (), (), ())
    candidates = Candidates()
    claims = automatic_endpoint_claim_candidates(
        resource_key="endpoint:new",
        holder_key="new-holder",
        generation=1,
        consumer_resource_key="service:new",
        allocation_id="new-allocation",
        purpose="test",
        host="127.0.0.1",
        authority=snapshot,
        candidates=candidates,
        probe=Probe(),
        owner_scope=PLATFORM_SCOPE,
        scope_generation=1,
        scope_lease_id=None,
    )
    assert candidates.requested[1] == 1
    assert len(claims) == 1
    projected = tuple(endpoint_placement_from_claim(row) for row in claims)
    assert tuple(row.endpoint.port for row in projected) == (8100,)
    assert all(row.consumer_resource_key == "service:new" for row in projected)


def test_authority_lease_ignores_wall_clock_jumps(tmp_path: Path) -> None:
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    clock = ManualLeaseClock(
        elapsed_seconds=10.0,
        wall_epoch_seconds=1_000_000.0,
    )
    authority = UniversalResourceAuthority(
        tmp_path / "authority.sqlite",
        clock=clock,
    )
    lease = _acquire_platform_ttl(authority,
        lease_id="lease",
        resource_key="resource",
        holder_key="holder",
        ttl_seconds=20.0,
    )
    clock.jump_wall(10_000_000.0)
    assert authority.active_leases("resource") == (lease,)
    clock.jump_wall(-20_000_000.0)
    assert authority.active_leases("resource") == (lease,)
    clock.advance(21.0, wall_seconds=0.0)
    assert authority.active_leases("resource") == ()


def test_authority_lease_uses_suspend_aware_elapsed_time(tmp_path: Path) -> None:
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    clock = ManualLeaseClock(elapsed_seconds=5.0)
    authority = UniversalResourceAuthority(
        tmp_path / "authority.sqlite",
        clock=clock,
    )
    _acquire_platform_ttl(authority,
        lease_id="lease",
        resource_key="resource",
        holder_key="holder",
        ttl_seconds=30.0,
    )
    clock.advance(31.0, wall_seconds=0.0)
    assert authority.active_leases("resource") == ()


def test_same_host_reboot_advances_resource_generation_once(tmp_path: Path) -> None:
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    path = tmp_path / "authority.sqlite"
    clock = ManualLeaseClock(boot_seed="boot-a")
    authority = UniversalResourceAuthority(path, clock=clock)
    first = authority.ensure_generation("resource")
    _acquire_platform_ttl(authority,
        lease_id="lease",
        resource_key="resource",
        holder_key="holder",
        ttl_seconds=300.0,
    )
    clock.reboot(boot_seed="boot-b")
    # Any lease observation detects the new boot and performs one global fence.
    assert authority.active_leases("resource") == ()
    second = authority.generation("resource")
    assert second is not None
    assert second.generation == first.generation + 1

    reopened = UniversalResourceAuthority(path, clock=clock)
    assert reopened.generation("resource") == second


def test_different_host_cannot_take_over_authority_clock_domain(tmp_path: Path) -> None:
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    path = tmp_path / "authority.sqlite"
    UniversalResourceAuthority(
        path,
        clock=ManualLeaseClock(host_seed="host-a"),
    )
    with pytest.raises(RuntimeError, match="different host clock domain"):
        UniversalResourceAuthority(
            path,
            clock=ManualLeaseClock(host_seed="host-b"),
        )


def test_delayed_old_lease_release_cannot_mutate_new_generation(tmp_path: Path) -> None:
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    path = tmp_path / "authority.sqlite"
    clock = ManualLeaseClock(boot_seed="boot-a")
    authority = UniversalResourceAuthority(path, clock=clock)
    old = _acquire_platform_exclusive_ttl(authority,
        lease_id="stable-lease-key",
        resource_key="recovery",
        holder_key="owner",
        ttl_seconds=300.0,
        metadata={"kind": "recovery"},
    )
    clock.reboot(boot_seed="boot-b")
    assert authority.active_leases("recovery") == ()
    new = _acquire_platform_exclusive_ttl(authority,
        lease_id="stable-lease-key",
        resource_key="recovery",
        holder_key="owner",
        ttl_seconds=300.0,
        metadata={"kind": "recovery"},
    )
    assert lease_field(new, "generation") == lease_field(old, "generation") + 1
    with pytest.raises(RuntimeError, match="different generation"):
        authority.release_lease(old)
    assert authority.active_leases("recovery") == (new,)


def test_delayed_old_lease_renew_cannot_mutate_new_generation(tmp_path: Path) -> None:
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    path = tmp_path / "authority.sqlite"
    clock = ManualLeaseClock(boot_seed="boot-a")
    authority = UniversalResourceAuthority(path, clock=clock)
    old = _acquire_platform_exclusive_ttl(authority,
        lease_id="stable-lease-key",
        resource_key="recovery",
        holder_key="owner",
        ttl_seconds=300.0,
        metadata={"kind": "recovery"},
    )
    clock.reboot(boot_seed="boot-b")
    authority.active_leases("recovery")
    new = _acquire_platform_exclusive_ttl(authority,
        lease_id="stable-lease-key",
        resource_key="recovery",
        holder_key="owner",
        ttl_seconds=300.0,
        metadata={"kind": "recovery"},
    )
    with pytest.raises(RuntimeError, match="different generation"):
        authority.renew_lease(old, ttl_seconds=300.0)
    assert lease_field(authority.get_lease(lease_field(new, "lease_id")), "generation") == lease_field(new, "generation")


def test_reconcile_uses_point_reads_for_ticket_local_physical_actions(
    tmp_path: Path,
) -> None:
    class CountingAuthority(UniversalResourceAuthority):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self.snapshot_calls = 0

        def snapshot(self) -> AuthoritySnapshot:
            self.snapshot_calls += 1
            return super().snapshot()

    authority = CountingAuthority(tmp_path / "authority.sqlite")
    provider = _TicketProvider()
    topology = resource_topology(
        "single-service",
        resources=(
            resource_node(
                "service",
                kind="service",
                authority_key="service",
                realization=True,
            ),
        ),
    )

    def candidates(
        _snapshot: AuthoritySnapshot,
        generation: int,
    ) -> tuple[NoetriumUnit, ...]:
        return (_claim("service-claim", "service", generation=generation),)

    result = authority.reconcile(
        topology,
        claim_candidates={"service": candidates},
        realization_specs={
            "service": lambda _snapshot: ResourceRealizationSpec(
                "fake",
                {"name": "service"},
            )
        },
        providers={"fake": provider},
    )

    binding = result.binding_for("service")
    assert binding is not None
    assert provider.by_ticket[str(binding_field(binding, "ticket_id"))] == binding_field(binding, "physical_identity")
    # One global cut to plan, one for claim placement, one for spec compilation,
    # and one convergence cut. REALIZE/BIND use indexed point reads instead of
    # decoding every generation/claim/lease/ticket/binding again.
    assert authority.snapshot_calls <= 4


def test_candidate_admission_never_refolds_active_claims(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import noetrium_platform.infrastructure.resources.authority.runtime.authority as authority_runtime

    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    authority.declare_capacity(ResourceCapacity((("cpu", 100),)))
    authority.ensure_generation("incumbent")
    authority.acquire_claim(
        _platform_claim(
            "incumbent",
            "incumbent",
            "holder",
            1,
            (("cpu", 50),),
        )
    )
    generation = authority.ensure_generation("candidate")

    calls = 0
    original = authority_runtime.compose_claims

    def counted(claims, *, capacity=None):
        nonlocal calls
        calls += 1
        return original(claims, capacity=capacity)

    monkeypatch.setattr(authority_runtime, "compose_claims", counted)
    candidates = tuple(
        _platform_claim(
            f"candidate-{amount}",
            "candidate",
            "holder",
            generation.generation,
            (("cpu", amount),),
        )
        for amount in (*range(100, 50, -1), 50)
    )
    admitted = authority.admit_first(candidates)
    assert claim_field(admitted, "amounts") == (("cpu", 50),)
    assert calls == 0


def test_incremental_claim_aggregate_tracks_release_and_token_refcounts(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    authority.declare_capacity(ResourceCapacity((("cpu", 10),)))

    for key in ("shared-a", "shared-b", "exclusive"):
        authority.ensure_generation(key)

    first = _platform_claim(
        "shared-a",
        "shared-a",
        "holder-a",
        1,
        (("cpu", 4),),
        ("gpu:0",),
    )
    second = _platform_claim(
        "shared-b",
        "shared-b",
        "holder-b",
        1,
        (("cpu", 4),),
        ("gpu:0",),
    )
    exclusive = _platform_claim(
        "exclusive",
        "exclusive",
        "holder-c",
        1,
        (("cpu", 2),),
        (),
        ("gpu:0",),
    )

    authority.acquire_claim(first)
    authority.acquire_claim(second)
    with pytest.raises(ResourceClaimConflict, match="exclusive claim conflict"):
        authority.acquire_claim(exclusive)

    authority.release_claim(claim_field(first, "claim_id"))
    with pytest.raises(ResourceClaimConflict, match="exclusive claim conflict"):
        authority.acquire_claim(exclusive)

    authority.release_claim(claim_field(second, "claim_id"))
    granted_exclusive = authority.acquire_claim(exclusive)
    assert claim_field(granted_exclusive, "claim_id") == claim_field(exclusive, "claim_id")
    assert resource_truth_modality(granted_exclusive) is TruthModality.AUTHORIZED


def test_orphan_release_updates_incremental_claim_aggregate(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    authority.declare_capacity(ResourceCapacity((("cpu", 5),)))

    owner_generation = authority.ensure_generation("owner")
    owner_lease = authority.acquire_lease(
        _platform_lease(
            "owner-lease",
            "owner",
            "owner-holder",
            owner_generation.generation,
            None,
            False,
        )
    )

    authority.ensure_generation("orphan")
    orphan = _platform_claim(
        "orphan-claim",
        "orphan",
        "orphan-holder",
        1,
        (("cpu", 5),),
        owner_lease_id=lease_field(owner_lease, "lease_id"),
    )
    authority.acquire_claim(orphan)
    authority.release_lease(owner_lease)

    released = authority.reconcile_orphan_claims()
    assert tuple(claim_field(row, "claim_id") for row in released) == (
        claim_field(orphan, "claim_id"),
    )
    assert all(resource_truth_modality(row) is TruthModality.AUTHORIZED for row in released)

    authority.ensure_generation("replacement")
    replacement = _platform_claim(
        "replacement-claim",
        "replacement",
        "replacement-holder",
        1,
        (("cpu", 5),),
    )
    granted_replacement = authority.acquire_claim(replacement)
    assert claim_field(granted_replacement, "claim_id") == claim_field(replacement, "claim_id")
    assert resource_truth_modality(granted_replacement) is TruthModality.AUTHORIZED


def test_snapshot_scales_with_live_state_not_retired_history(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    generation = authority.ensure_generation("service")
    authority.acquire_claim(_claim("claim", "service"))

    lease = authority.acquire_lease(
        _platform_lease(
            "lease",
            "service",
            "consumer",
            generation.generation,
            None,
            False,
        )
    )

    ticket, producer = authority.prepare_realization(
        realization_key="service-realization",
        resource_key="service",
        generation=generation.generation,
        spec=ResourceRealizationSpec("fake", {"name": "service"}),
        holder_key="holder",
    )
    assert producer
    provider = _TicketProvider()
    provider.realize({}, ticket)
    authority.bind(ticket_field(ticket, "ticket_id"), provider.observe(ticket))

    authority.release_lease(lease)
    retiring = authority.begin_retire(ticket_field(ticket, "ticket_id"))
    observation = provider.retire(retiring, retiring)
    authority.complete_retire(ticket_field(retiring, "ticket_id"), observation)
    authority.release_claim("claim")

    snapshot = authority.snapshot()
    # The durable generation remains as the fencing epoch. Historical released
    # leases and retired effects stay in SQLite evidence, but are not part of
    # the live dynamic cut used by placement/reconciliation.
    assert snapshot.generation_for("service") == generation
    assert snapshot.claims == ()
    assert snapshot.leases == ()
    assert snapshot.tickets == ()
    assert snapshot.bindings == ()

    # Historical rows still exist durably and are not silently deleted.
    with authority._reader() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM resource_authority_leases"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM resource_authority_tickets"
        ).fetchone()[0] == 1


def test_topology_local_snapshot_excludes_unrelated_live_resources(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    for key in ("local", "foreign"):
        generation = authority.ensure_generation(key)
        authority.acquire_claim(
            _claim(f"{key}-claim", key, generation=generation.generation)
        )
        authority.acquire_lease(
            _platform_lease(
                f"{key}-lease",
                key,
                f"{key}-holder",
                generation.generation,
                None,
                False,
            )
        )

    local = authority._snapshot_for_resource_keys(frozenset({"local"}))
    assert tuple(row.resource_key for row in local.generations) == ("local",)
    assert tuple(str(claim_field(row, "resource_key")) for row in local.claims) == ("local",)
    assert tuple(str(lease_field(row, "resource_key")) for row in local.leases) == ("local",)
    assert local.tickets == ()
    assert local.bindings == ()

    global_snapshot = authority.snapshot()
    assert {row.resource_key for row in global_snapshot.generations} == {
        "local",
        "foreign",
        "scope:platform:default",
    }
    assert {str(claim_field(row, "resource_key")) for row in global_snapshot.claims} == {
        "local",
        "foreign",
    }


def test_reconcile_planner_uses_topology_local_cut_but_admission_stays_global(
    tmp_path: Path,
) -> None:
    class CutCountingAuthority(UniversalResourceAuthority):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self.local_cut_calls = 0
            self.global_cut_calls = 0

        def _snapshot_for_resource_keys(
            self,
            resource_keys: frozenset[str] | None,
        ) -> AuthoritySnapshot:
            if resource_keys is None:
                self.global_cut_calls += 1
            else:
                self.local_cut_calls += 1
            return super()._snapshot_for_resource_keys(resource_keys)

    authority = CutCountingAuthority(tmp_path / "authority.sqlite")
    # Unrelated live state must not enter planner cuts.
    foreign_generation = authority.ensure_generation("foreign")
    authority.acquire_claim(
        _claim(
            "foreign-claim",
            "foreign",
            generation=foreign_generation.generation,
        )
    )

    topology = resource_topology(
        "local-topology",
        resources=(
            resource_node(
                "local",
                kind="compute",
                authority_key="local",
            ),
        ),
    )

    def candidates(
        snapshot: AuthoritySnapshot,
        generation: int,
    ) -> tuple[NoetriumUnit, ...]:
        # Admission compilers intentionally retain a global cut so they can see
        # other consumers competing for physical capacity.
        assert any(claim_field(row, "resource_key") == "foreign" for row in snapshot.claims)
        return (_claim("local-claim", "local", generation=generation),)

    result = authority.reconcile(
        topology,
        claim_candidates={"local": candidates},
        realization_specs={},
        providers={},
    )
    assert result.current_claims_for("local")
    assert authority.local_cut_calls >= 2
    # One global admission cut is sufficient: the candidate compiler proves
    # visibility of the foreign claim above; requiring a duplicate global
    # scan would encode an avoidable performance regression in this test.
    assert authority.global_cut_calls >= 1


def test_warm_authority_attach_does_not_wait_for_unrelated_writer_lock(
    tmp_path: Path,
) -> None:
    import sqlite3
    import time
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    path = tmp_path / "authority.sqlite"
    clock = ManualLeaseClock(boot_seed="same-boot")
    first = UniversalResourceAuthority(path, clock=clock)
    generation = first.ensure_generation("resource")

    blocker = sqlite3.connect(path, timeout=0.1)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        attached = UniversalResourceAuthority(
            path,
            timeout_seconds=0.1,
            clock=clock,
        )
        elapsed = time.monotonic() - started
        # A warm attach is a read proof and must not queue behind a writer.
        assert elapsed < 0.5
        assert attached.generation("resource") == generation
    finally:
        blocker.rollback()
        blocker.close()


def test_authority_schema_marker_is_published_only_after_full_initialization(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authority.sqlite"
    UniversalResourceAuthority(path)
    import sqlite3
    with sqlite3.connect(path) as db:
        value = db.execute(
            "SELECT value FROM resource_authority_meta "
            "WHERE key='resource-authority-schema'"
        ).fetchone()
    assert value == ("resource-authority-v9",)



def test_authority_serializes_sem_scale_concurrent_mutations(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(
        tmp_path / "authority.sqlite",
        timeout_seconds=0.05,
    )
    authority.declare_capacity(ResourceCapacity((("cpu", 256),)))

    def mutate(index: int) -> tuple[str, int]:
        key = f"demo-lifetime-{index}"
        generation = authority.ensure_generation(key)
        claim = _platform_claim(
            f"claim-{index}",
            key,
            f"holder-{index}",
            generation.generation,
            (("cpu", 1),),
            (),
            (),
        )
        authority.acquire_claim(claim)
        return key, generation.generation

    with ThreadPoolExecutor(max_workers=70) as pool:
        rows = tuple(pool.map(mutate, range(70)))

    assert len(rows) == 70
    snapshot = authority.snapshot()
    assert len(snapshot.claims) == 70
    assert {str(claim_field(row, "resource_key")) for row in snapshot.claims} == {
        f"demo-lifetime-{index}" for index in range(70)
    }
    authority.close()


def test_reconcile_replans_after_concurrent_candidate_claim(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    topology = resource_topology(
        "concurrent-placement",
        resources=(
            resource_node(
                "endpoint",
                kind="network-endpoint",
                authority_key="target-endpoint",
            ),
        ),
    )
    calls = 0

    def candidates(
        _snapshot: AuthoritySnapshot,
        generation: int,
    ) -> tuple[NoetriumUnit, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            other_generation = authority.ensure_generation("other-endpoint")
            authority.acquire_claim(
                _platform_claim(
                    "other-port",
                    "other-endpoint",
                    "other-holder",
                    other_generation.generation,
                    exclusive=("tcp://127.0.0.1:40001",),
                )
            )
            token = "tcp://127.0.0.1:40001"
        else:
            token = "tcp://127.0.0.1:40002"
        return (
            _platform_claim(
                f"target-port-{calls}",
                "target-endpoint",
                "target-holder",
                generation,
                exclusive=(token,),
            ),
        )

    result = authority.reconcile(
        topology,
        claim_candidates={"endpoint": candidates},
        realization_specs={},
        providers={},
    )

    current = result.current_claims_for("target-endpoint")
    assert len(current) == 1
    assert claim_field(current[0], "exclusive") == ("tcp://127.0.0.1:40002",)
    assert calls == 2


def test_binding_for_physical_is_an_indexed_point_lookup(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    generation = authority.ensure_generation("service")
    authority.acquire_claim(_claim("claim", "service"))
    ticket, producer = authority.prepare_realization(
        realization_key="service-realization",
        resource_key="service",
        generation=generation.generation,
        spec=ResourceRealizationSpec("fake", {"name": "service"}),
        holder_key="holder",
    )
    assert producer
    identity = physical_identity("fake", "physical-1")
    authority.bind(
        ticket_field(ticket, "ticket_id"),
        resource_observation(
            "service",
            generation.generation,
            ticket_field(ticket, "ticket_id"),
            ticket_field(ticket, "spec_digest"),
            True,
            True,
            identity,
        ),
    )

    binding = authority.binding_for_physical("fake", "physical-1")
    assert binding is not None
    assert binding_field(binding, "ticket_id") == ticket_field(ticket, "ticket_id")
    assert binding_field(binding, "resource_key") == "service"
    assert authority.binding_for_physical("fake", "missing") is None


def test_resource_authority_read_snapshots_release_reader_sessions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from contextlib import contextmanager

    import noetrium_platform.infrastructure.resources.authority.runtime.authority as authority_runtime

    real_reader = authority_runtime.durable_sqlite_reader
    active = 0
    opened = 0

    @contextmanager
    def tracked_reader(*args, **kwargs):
        nonlocal active, opened
        with real_reader(*args, **kwargs) as db:
            active += 1
            opened += 1
            try:
                yield db
            finally:
                active -= 1

    monkeypatch.setattr(authority_runtime, "durable_sqlite_reader", tracked_reader)
    authority = UniversalResourceAuthority(tmp_path / "authority-reader-lifetime.sqlite")
    authority.ensure_generation("resource")

    for _ in range(64):
        snapshot = authority.snapshot()
        assert snapshot.generation_for("resource") is not None
        assert active == 0

    assert opened >= 64
    assert active == 0
    authority.close()


def test_candidate_admission_materializes_one_batched_usage_view(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    authority.declare_capacity(ResourceCapacity((("cpu", 100),)))
    authority.ensure_generation("incumbent")
    authority.acquire_claim(
        _platform_claim(
            "incumbent",
            "incumbent",
            "holder",
            1,
            (("cpu", 50),),
        )
    )
    generation = authority.ensure_generation("candidate")
    candidates = tuple(
        _platform_claim(
            f"candidate-{amount}",
            "candidate",
            "holder",
            generation.generation,
            (("cpu", amount),),
        )
        for amount in (*range(100, 50, -1), 50)
    )

    calls = 0
    original = UniversalResourceAuthority._claim_usage_view_locked.__func__

    def counted(cls, conn, claims):
        nonlocal calls
        calls += 1
        return original(cls, conn, claims)

    monkeypatch.setattr(
        UniversalResourceAuthority,
        "_claim_usage_view_locked",
        classmethod(counted),
    )
    admitted = authority.admit_first(candidates)
    assert claim_field(admitted, "amounts") == (("cpu", 50),)
    assert calls == 1


def test_parent_realization_retirement_linearizes_with_child_admission(tmp_path: Path) -> None:
    """The Authority writer cut closes both orders of the retire/admit race."""
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    parent_generation = authority.ensure_generation("shared-physical")
    child_generation = authority.ensure_generation("dependent-physical")
    parent = _platform_claim(
        "parent-claim",
        "shared-physical",
        "platform-parent",
        parent_generation.generation,
        attributes={"kind": "physical-parent"},
    )
    authority.acquire_claim(parent)
    ticket, _producer = authority.prepare_realization(
        realization_key="shared-physical-realization",
        resource_key="shared-physical",
        generation=parent_generation.generation,
        spec=ResourceRealizationSpec("fake", {"name": "parent"}),
        holder_key="platform-parent",
    )

    def child(claim_id: str) -> NoetriumUnit:
        return _platform_claim(
            claim_id,
            "dependent-physical",
            "child",
            child_generation.generation,
            attributes={
                "kind": "physical-child",
                "parent_claim_id": "parent-claim",
                "parent_resource_key": "shared-physical",
            },
        )

    authority.admit_bundle(((child("child-first"),),))
    with pytest.raises(ResourceClaimConflict, match="dependent claim remains"):
        authority.begin_retire(ticket_field(ticket, "ticket_id"))

    authority.release_claim("child-first")
    retiring = authority.begin_retire(ticket_field(ticket, "ticket_id"))
    assert ticket_field(retiring, "state") is TicketState.RETIRING
    with pytest.raises(ResourceClaimConflict, match="retiring parent realization"):
        authority.admit_bundle(((child("retirement-first"),),))


def _delay_direct_claim_mutation(authority, monkeypatch):
    original = authority._execute_claim_mutation_direct
    entered = Event()
    proceed = Event()

    def delayed_direct(pending):
        entered.set()
        assert proceed.wait(2.0), "claim mutation followers did not enqueue"
        return original(pending)

    monkeypatch.setattr(authority, "_execute_claim_mutation_direct", delayed_direct)
    return entered, proceed


def _wait_for_claim_mutation_queue(authority, expected: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with authority._claim_mutation_lock:
            if len(authority._claim_mutation_queue) >= expected:
                return
        time.sleep(0.001)
    raise AssertionError(f"claim mutation queue did not reach {expected}")


def test_grouped_claim_failure_rolls_back_event_cache_without_poisoning_follower(
    tmp_path: Path, monkeypatch,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "grouped-savepoint.sqlite")
    try:
        authority.declare_capacity(ResourceCapacity((("cpu", 1),)))
        generation_a = authority.ensure_generation("resource:a").generation
        generation_b = authority.ensure_generation("resource:b").generation
        generation_c = authority.ensure_generation("resource:c").generation
        seed_generation = authority.ensure_generation("resource:seed").generation
        seed = authority.admit_bundle(((
            _platform_claim("seed", "resource:seed", "holder:seed", seed_generation),
        ),))[0]
        first = _platform_claim(
            "first", "resource:a", "holder:first", generation_a,
            amounts=(("cpu", 1),),
        )
        impossible = _platform_claim(
            "impossible", "resource:b", "holder:impossible", generation_b,
            amounts=(("cpu", 1),),
        )
        follower = _platform_claim(
            "follower", "resource:c", "holder:follower", generation_c,
            amounts=(("cpu", 1),),
        )
        entered, proceed = _delay_direct_claim_mutation(authority, monkeypatch)
        with ThreadPoolExecutor(max_workers=3) as pool:
            leader = pool.submit(authority.release_claim, claim_field(seed, "claim_id"))
            assert entered.wait(1.0)
            failed = pool.submit(
                authority.admit_bundle,
                ((first,), (impossible,)),
            )
            _wait_for_claim_mutation_queue(authority, 1)
            successful = pool.submit(authority.admit_bundle, ((follower,),))
            _wait_for_claim_mutation_queue(authority, 2)
            proceed.set()
            assert claim_field(leader.result(timeout=2.0), "claim_id") == "seed"
            with pytest.raises(ResourceClaimConflict):
                failed.result(timeout=2.0)
            admitted = successful.result(timeout=2.0)
        assert tuple(claim_field(row, "claim_id") for row in admitted) == ("follower",)
        assert tuple(claim_field(row, "claim_id") for row in authority.snapshot().claims) == (
            "follower",
        )
        assert authority.verify_projection_rebuild() == authority.snapshot()
    finally:
        authority.close()


def test_grouped_release_invalidates_usage_before_replacement_admission(
    tmp_path: Path, monkeypatch,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "grouped-release.sqlite")
    try:
        authority.declare_capacity(ResourceCapacity((("cpu", 1),)))
        generation = authority.ensure_generation("resource").generation
        old = authority.admit_bundle(((
            _platform_claim(
                "old", "resource", "holder:old", generation,
                amounts=(("cpu", 1),),
            ),
        ),))[0]
        replacement = _platform_claim(
            "replacement", "resource", "holder:new", generation,
            amounts=(("cpu", 1),),
        )
        seed_generation = authority.ensure_generation("resource:seed").generation
        seed = authority.admit_bundle(((
            _platform_claim("seed", "resource:seed", "holder:seed", seed_generation),
        ),))[0]
        entered, proceed = _delay_direct_claim_mutation(authority, monkeypatch)
        with ThreadPoolExecutor(max_workers=3) as pool:
            leader = pool.submit(authority.release_claim, claim_field(seed, "claim_id"))
            assert entered.wait(1.0)
            released = pool.submit(authority.release_claim, claim_field(old, "claim_id"))
            _wait_for_claim_mutation_queue(authority, 1)
            admitted = pool.submit(authority.admit_bundle, ((replacement,),))
            _wait_for_claim_mutation_queue(authority, 2)
            proceed.set()
            assert claim_field(leader.result(timeout=2.0), "claim_id") == "seed"
            assert claim_field(released.result(timeout=2.0), "claim_id") == "old"
            replacement_result = admitted.result(timeout=2.0)
        assert tuple(claim_field(row, "claim_id") for row in replacement_result) == (
            "replacement",
        )
        assert tuple(claim_field(row, "claim_id") for row in authority.snapshot().claims) == (
            "replacement",
        )
    finally:
        authority.close()


def test_grouped_orphan_horizon_rechecks_after_exact_owner_expiry(
    tmp_path: Path, monkeypatch,
) -> None:
    from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock

    clock = ManualLeaseClock(elapsed_seconds=10.0, wall_epoch_seconds=1_000.0)
    authority = UniversalResourceAuthority(
        tmp_path / "grouped-expiry.sqlite", clock=clock,
    )
    try:
        authority.declare_capacity(ResourceCapacity((("cpu", 2),)))
        generation = authority.ensure_generation("resource").generation
        owner = authority.acquire_ttl_lease(
            lease_id="owner", resource_key="owner", holder_key="owner",
            owner_scope=PLATFORM_SCOPE, ttl_seconds=1.0,
            metadata={"kind": "grouped-expiry-owner"},
        )
        live_owner = authority.acquire_ttl_lease(
            lease_id="live-owner", resource_key="live-owner", holder_key="live-owner",
            owner_scope=PLATFORM_SCOPE, ttl_seconds=30.0,
            metadata={"kind": "grouped-expiry-live-owner"},
        )
        before_expiry = _platform_claim(
            "before", "resource", "holder:before", generation,
            amounts=(("cpu", 1),), owner_lease_id=lease_field(owner, "lease_id"),
        )
        after_expiry = _platform_claim(
            "after", "resource", "holder:after", generation,
            amounts=(("cpu", 1),),
            owner_lease_id=lease_field(live_owner, "lease_id"),
        )
        seed_generation = authority.ensure_generation("resource:seed").generation
        seed = authority.admit_bundle(((
            _platform_claim("seed", "resource:seed", "holder:seed", seed_generation),
        ),))[0]
        entered, proceed = _delay_direct_claim_mutation(authority, monkeypatch)
        with ThreadPoolExecutor(max_workers=3) as pool:
            leader = pool.submit(authority.release_claim, claim_field(seed, "claim_id"))
            assert entered.wait(1.0)
            first = pool.submit(authority.admit_bundle, ((before_expiry,),))
            _wait_for_claim_mutation_queue(authority, 1)
            clock.advance(2.0, wall_seconds=0.0)
            second = pool.submit(authority.admit_bundle, ((after_expiry,),))
            _wait_for_claim_mutation_queue(authority, 2)
            proceed.set()
            assert claim_field(leader.result(timeout=2.0), "claim_id") == "seed"
            assert claim_field(first.result(timeout=2.0)[0], "claim_id") == "before"
            assert claim_field(second.result(timeout=2.0)[0], "claim_id") == "after"
        assert tuple(
            claim_field(row, "claim_id") for row in authority.snapshot().claims
        ) == ("after",)
        assert authority.verify_projection_rebuild() == authority.snapshot()
    finally:
        authority.close()
