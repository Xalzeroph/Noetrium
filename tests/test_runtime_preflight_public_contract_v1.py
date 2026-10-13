from __future__ import annotations

from noetrium_platform.foundation.scope.api import scope_unit
from noetrium_platform.infrastructure.reliability.recovery.api import (
    RecoveryActionCode,
    RecoveryAutomation,
    RecoveryDecisionReport,
    RecoveryRecommendation,
)
from noetrium_platform.infrastructure.resources.authority import (
    AuthoritySnapshot,
    resource_claim,
)
from noetrium_platform.infrastructure.resources.compute import api as compute_api
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputePlacementUnavailable,
    ComputeRequirement,
)
from noetrium_platform.infrastructure.resources.compute.placement import (
    compute_claim_candidates,
    compute_placement_from_claim,
)
from noetrium_platform.infrastructure.lifecycle.server.health.api import (
    ServerDiagnosticIssue,
    ServerDiagnosticReport,
    ServerDiagnosticSeverity,
    ServerDiagnosticStatus,
    ServerHealthReport,
)
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerCommandResult
from noetrium_platform.foundation.scope.api import NoetriumUnit, ScopeKind
from tests.resource_compute_support import idle_gpu_runtime_observer


def _server(status: ServerDiagnosticStatus) -> ServerDiagnosticReport:
    command = ServerCommandResult("server-2", "health", 0, "ok", "")
    health = ServerHealthReport("server-2", True, "host", "3.12", "2.55", "3.4", command, True)
    issues = () if status is ServerDiagnosticStatus.READY else (
        ServerDiagnosticIssue(
            "runtime:not-ready",
            ServerDiagnosticSeverity.ERROR,
            "runtime is not ready",
            evidence_refs=("server:server-2",),
            recommended_action="inspect_health_checks",
        ),
    )
    return ServerDiagnosticReport(
        "server-2", "p" * 64, "ops.log", health, (), (), None, issues, status
    )


def _recovery(blocked: bool) -> RecoveryDecisionReport:
    if not blocked:
        return RecoveryDecisionReport(())
    return RecoveryDecisionReport((RecoveryRecommendation(
        "runtime",
        RecoveryActionCode.BLOCK_IDENTITY_DRIFT,
        RecoveryAutomation.FORBIDDEN,
        ("identity_drift",),
    ),))


def _candidate_host_ids(
    hosts: tuple[ComputeHost, ...],
    requirement: ComputeRequirement,
    *,
    scope: NoetriumUnit,
    snapshot: AuthoritySnapshot | None = None,
) -> tuple[str, ...]:
    gpu_ids = tuple(gpu.gpu_id for host in hosts for gpu in host.gpus)
    try:
        claims = compute_claim_candidates(
            resource_key="preflight:compute",
            holder_key="preflight",
            generation=1,
            consumer_resource_key="preflight:consumer",
            requirement=requirement,
            hosts=hosts,
            authority=snapshot or AuthoritySnapshot((), (), (), (), ()),
            placement_scope=scope,
            gpu_runtime=idle_gpu_runtime_observer(*gpu_ids).snapshot(),
        )
    except ComputePlacementUnavailable:
        return ()
    return tuple(compute_placement_from_claim(row).host_id for row in claims)


def test_public_runtime_resource_recovery_facts_are_sufficient_for_read_only_preflight() -> None:
    scope = scope_unit(ScopeKind.RUN, "run-1")
    requirement = ComputeRequirement(
        cpu_cores=4,
        memory_bytes=8 * 1024,
        gpu_count=1,
        minimum_gpu_memory_bytes=16 * 1024,
        required_labels=(("os", "linux"),),
    )
    hosts = (
        ComputeHost(
            "local", scope, 8, 32 * 1024,
            (ComputeGPU("g0", 8 * 1024),),
            (("os", "windows"),),
        ),
        ComputeHost(
            "server-2", scope, 8, 32 * 1024,
            (ComputeGPU("g1", 24 * 1024),),
            (("os", "linux"),),
        ),
    )
    assert _candidate_host_ids(hosts, requirement, scope=scope) == ("server-2",)
    assert _server(ServerDiagnosticStatus.READY).status is ServerDiagnosticStatus.READY
    assert _recovery(False).blocked == ()


def test_public_facts_fail_closed_without_mutating_authority_snapshot() -> None:
    scope = scope_unit(ScopeKind.RUN, "run-2")
    hosts = (ComputeHost("small", scope, 4, 4096),)
    snapshot = AuthoritySnapshot((), (), (), (), ())
    before = snapshot
    assert _candidate_host_ids(
        hosts,
        ComputeRequirement(cpu_cores=64, memory_bytes=1024),
        scope=scope,
        snapshot=snapshot,
    ) == ()
    assert snapshot == before
    assert _server(ServerDiagnosticStatus.REMOTE_NOT_READY).issues
    assert _recovery(True).blocked


def test_preflight_projects_live_authority_usage_without_mutating_it() -> None:
    scope = scope_unit(ScopeKind.RUN, "run-capacity")
    requirement = ComputeRequirement(cpu_cores=4, memory_bytes=4096)
    host = ComputeHost("server-2", scope, 4, 4096)
    assert _candidate_host_ids((host,), requirement, scope=scope) == ("server-2",)

    occupied = resource_claim(
        "existing",
        "compute:existing",
        "holder",
        1,
        amounts=(
            ("compute:server-2:cpu-cores", 4),
            ("compute:server-2:memory-bytes", 4096),
        ),
        attributes={
            "kind": "compute",
            "host_id": "server-2",
            "cpu_cores": 4,
            "memory_bytes": 4096,
            "gpu_ids": [],
            "gpu_sharing_mode": "idle-only",
            "gpu_memory_reservation_bytes": [],
            "consumer_resource_key": "service:existing",
        },
    )
    snapshot = AuthoritySnapshot((), (occupied,), (), (), ())
    assert _candidate_host_ids(
        (host,), requirement, scope=scope, snapshot=snapshot
    ) == ()
    assert snapshot.claims == (occupied,)


def test_compute_public_api_has_no_mutating_scheduler_surface() -> None:
    assert not hasattr(compute_api, "ComputeSchedulerPort")
    assert not hasattr(compute_api, "ComputeCandidatePort")
    assert not hasattr(compute_api, "ComputeAllocation")
