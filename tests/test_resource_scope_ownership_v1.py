from __future__ import annotations

import pytest

from noetrium_platform.foundation.governance.api import (
    PLATFORM_SCOPE,
    ScopeKind,
    scope_key,
    scope_unit,
)
from noetrium_platform.foundation.kernel.kernel import ManualLeaseClock
from noetrium_platform.infrastructure.resources.authority.api import (
    claim_field,
    lease_field,
    resource_claim,
)
from noetrium_platform.infrastructure.resources.authority.runtime.authority import (
    ResourceClaimConflict,
    UniversalResourceAuthority,
)


def _scope_chain(authority: UniversalResourceAuthority):
    experiment = scope_unit(ScopeKind.EXPERIMENT, "experiment-1")
    run = scope_unit(ScopeKind.RUN, "run-1")
    branch = scope_unit(ScopeKind.BRANCH, "branch-1")
    run_lease = authority.acquire_scope_lease(
        scope=run,
        parent_scope=experiment,
        holder_key=scope_key(run),
        ttl_seconds=10.0,
    )
    branch_lease = authority.acquire_scope_lease(
        scope=branch,
        parent_scope=run,
        parent_scope_lease=run_lease,
        holder_key=scope_key(branch),
        ttl_seconds=100.0,
    )
    return experiment, run, branch, run_lease, branch_lease


def test_parent_scope_expiry_immediately_orphans_child_claim(tmp_path) -> None:
    clock = ManualLeaseClock()
    authority = UniversalResourceAuthority(tmp_path / "resources.sqlite", clock=clock)
    try:
        _experiment, _run, branch, _run_lease, branch_lease = _scope_chain(authority)
        branch_generation, branch_scope_lease_id = authority.scope_ownership_cut(
            branch,
            scope_lease=branch_lease,
        )
        resource_generation = authority.ensure_generation("resource:branch-1")
        claim = authority.acquire_claim(
            resource_claim(
                claim_id="claim:branch-1",
                resource_key=resource_generation.resource_key,
                holder_key=scope_key(branch),
                generation=resource_generation.generation,
                owner_scope=branch,
                scope_generation=branch_generation.generation,
                scope_lease_id=branch_scope_lease_id,
                owner_lease_id=None,
            )
        )
        assert authority.orphaned_claim_groups() == ()

        # RUN expires at +10s while BRANCH itself remains valid for +100s.
        # Recursive Scope liveness must make the child unauthorized immediately.
        clock.advance(11.0)
        groups = authority.orphaned_claim_groups()
        assert len(groups) == 1
        group_lease_id, claims = groups[0]
        assert group_lease_id == lease_field(branch_lease, "lease_id")
        assert tuple(claim_field(row, "claim_id") for row in claims) == (
            claim_field(claim, "claim_id"),
        )
        released = authority.reconcile_orphan_claims()
        assert tuple(claim_field(row, "claim_id") for row in released) == (
            claim_field(claim, "claim_id"),
        )
    finally:
        authority.close()


def test_child_scope_renewal_fails_after_parent_expiry(tmp_path) -> None:
    clock = ManualLeaseClock()
    authority = UniversalResourceAuthority(tmp_path / "resources.sqlite", clock=clock)
    try:
        _experiment, _run, _branch, _run_lease, branch_lease = _scope_chain(authority)
        clock.advance(11.0)
        with pytest.raises(ResourceClaimConflict):
            authority.renew_lease(branch_lease, ttl_seconds=100.0)
    finally:
        authority.close()


def test_static_platform_scope_never_accepts_scope_lease(tmp_path) -> None:
    clock = ManualLeaseClock()
    authority = UniversalResourceAuthority(tmp_path / "resources.sqlite", clock=clock)
    try:
        generation, lease_id = authority.scope_ownership_cut(PLATFORM_SCOPE)
        assert generation.generation == 1
        assert lease_id is None
        with pytest.raises(ValueError):
            authority.acquire_scope_lease(
                scope=PLATFORM_SCOPE,
                parent_scope=PLATFORM_SCOPE,
                holder_key=scope_key(PLATFORM_SCOPE),
                ttl_seconds=10.0,
            )
    finally:
        authority.close()
