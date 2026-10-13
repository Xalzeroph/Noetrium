from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.api import (
    ScopeKind,
    scope_key,
    scope_unit,
)
from noetrium_platform.foundation.kernel.kernel import ManualLeaseClock
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
    claim_field,
    lease_field,
    resource_claim,
)


def test_claim_kind_orphan_projection_is_sparse_and_reconciles_exact_kind(
    tmp_path: Path,
) -> None:
    clock = ManualLeaseClock()
    authority = UniversalResourceAuthority(
        tmp_path / "authority.sqlite",
        clock=clock,
    )
    try:
        experiment = scope_unit(ScopeKind.EXPERIMENT, "experiment")
        run = scope_unit(ScopeKind.RUN, "expired-run")
        run_lease = authority.acquire_scope_lease(
            scope=run,
            parent_scope=experiment,
            holder_key=scope_key(run),
            ttl_seconds=10.0,
        )
        generation, scope_lease_id = authority.scope_ownership_cut(
            run,
            scope_lease=run_lease,
        )

        generation_a = authority.ensure_generation("minecraft-test")
        generation_b = authority.ensure_generation("unrelated-test")
        minecraft = authority.acquire_claim(
            resource_claim(
                claim_id="minecraft-claim",
                resource_key="minecraft-test",
                holder_key="minecraft-holder",
                generation=generation_a.generation,
                owner_scope=run,
                scope_generation=generation.generation,
                scope_lease_id=scope_lease_id,
                owner_lease_id=None,
                attributes={"kind": "minecraft-server"},
            )
        )
        authority.acquire_claim(
            resource_claim(
                claim_id="unrelated-claim",
                resource_key="unrelated-test",
                holder_key="unrelated-holder",
                generation=generation_b.generation,
                owner_scope=run,
                scope_generation=generation.generation,
                scope_lease_id=scope_lease_id,
                owner_lease_id=None,
                attributes={"kind": "unrelated"},
            )
        )

        assert authority.orphaned_claim_groups_for_claim_kinds(
            frozenset({"minecraft-server"})
        ) == ()

        clock.advance(11.0)
        groups = authority.orphaned_claim_groups_for_claim_kinds(
            frozenset({"minecraft-server"})
        )
        assert len(groups) == 1
        assert groups[0][0] == lease_field(run_lease, "lease_id")
        assert [
            str(claim_field(claim, "claim_id"))
            for _owner, claims in groups
            for claim in claims
        ] == [str(claim_field(minecraft, "claim_id"))]

        released = authority.reconcile_orphan_claims_for_claim_kinds(
            frozenset({"minecraft-server"})
        )
        assert [
            str(claim_field(claim, "claim_id"))
            for claim in released
        ] == ["minecraft-claim"]

        unrelated = authority.snapshot_for_resource_keys(
            frozenset({"unrelated-test"})
        ).claims
        assert len(unrelated) == 1
        assert claim_field(unrelated[0], "claim_id") == "unrelated-claim"
    finally:
        authority.close()
