from __future__ import annotations

from uuid import uuid4

import pytest

from model_admission_test_support import make_model_admission_registry
from noetrium_platform.infrastructure.resources.authority import (
    ResourceClaimConflict, claim_field, lease_field, resource_claim,
)


def test_parent_borrow_is_admitted_and_retired_by_the_one_resource_authority() -> None:
    registry = make_model_admission_registry()
    authority = registry._test_authority
    controller = registry.controller_for(
        deployment_id="owned-resource", deployment_generation="a" * 64,
        qualified_capacity=2, continuity_capacity=1,
    )
    owner = registry._test_owner_lease
    parent_id = "model-continuity:declared-parent"
    def make_child(reference: str, *, parent_reference: str):
        return resource_claim(
            claim_id=reference,
            resource_key=controller._continuity_resource_key,
            holder_key="child-holder:" + uuid4().hex,
            generation=controller._continuity_generation,
            owner_scope=lease_field(owner, "owner_scope"),
            scope_generation=int(lease_field(owner, "scope_generation")),
            scope_lease_id=lease_field(owner, "scope_lease_id"),
            owner_lease_id=lease_field(owner, "lease_id"),
            attributes={"kind": "test-resource-child", "parent_claim_id": parent_reference},
        )

    absent = make_child("parent-test:absent", parent_reference=parent_id)
    with pytest.raises(ResourceClaimConflict, match="no live parent"):
        authority.admit_bundle(((absent,),))

    parent = controller.try_reserve_continuity(owner_id="paper", flow_id="life")
    assert parent is not None
    child = make_child("parent-test:live", parent_reference=parent.claim_id)
    authorized = authority.admit_bundle(((child,),))[0]
    with pytest.raises(ResourceClaimConflict, match="active child"):
        parent.release()
    authority.release_claim("parent-test:live")
    parent.release()
    with pytest.raises(ResourceClaimConflict, match="no live parent"):
        authority.admit_bundle(((make_child("parent-test:retired", parent_reference=parent.claim_id),),))
    controller.close()
    registry.close()


def test_orphan_claims_release_children_before_parent_in_one_cut() -> None:
    registry = make_model_admission_registry()
    authority = registry._test_authority
    controller = registry.controller_for(
        deployment_id="orphan-family", deployment_generation="c" * 64,
        qualified_capacity=1, continuity_capacity=1,
    )
    parent = controller.try_reserve_continuity(
        owner_id="orphaned", flow_id="orphan-world",
    )
    assert parent is not None
    owner = registry._test_owner_lease
    child_id = "00-orphan-child"
    child = resource_claim(
        claim_id=child_id,
        resource_key=controller._continuity_resource_key,
        holder_key="child-holder:" + uuid4().hex,
        generation=controller._continuity_generation,
        owner_scope=lease_field(owner, "owner_scope"),
        scope_generation=int(lease_field(owner, "scope_generation")),
        scope_lease_id=lease_field(owner, "scope_lease_id"),
        owner_lease_id=lease_field(owner, "lease_id"),
        attributes={"kind": "model-continuity-borrow",
                    "parent_claim_id": parent.claim_id},
    )
    authority.admit_bundle(((child,),))
    authority.release_lease(owner)
    released = authority.reconcile_orphan_claims()
    assert {claim_field(c, "claim_id") for c in released} == {
        child_id, parent.claim_id,
    }
    assert controller._claims_at_cut()[1] == ()
    controller.close()
    registry.close()


def test_different_resource_claim_preserves_live_platform_parent() -> None:
    registry = make_model_admission_registry()
    authority = registry._test_authority
    controller = registry.controller_for(
        deployment_id="cross-resource-parent", deployment_generation="d" * 64,
        qualified_capacity=1, continuity_capacity=1,
    )
    parent = controller.try_reserve_continuity(owner_id="paper", flow_id="warm")
    assert parent is not None
    owner = registry._test_owner_lease
    child_key = "minecraft-server:separate"
    generation = authority.ensure_generation(child_key).generation
    child = resource_claim(
        claim_id="cross-resource:child", resource_key=child_key,
        holder_key="child:" + uuid4().hex, generation=generation,
        owner_scope=lease_field(owner, "owner_scope"),
        scope_generation=int(lease_field(owner, "scope_generation")),
        scope_lease_id=lease_field(owner, "scope_lease_id"),
        owner_lease_id=lease_field(owner, "lease_id"),
        attributes={"kind": "minecraft-server",
                    "parent_claim_id": parent.claim_id,
                    "parent_resource_key": controller._continuity_resource_key},
    )
    authority.admit_bundle(((child,),))
    with pytest.raises(ResourceClaimConflict, match="active child"):
        parent.release()
    authority.release_claim("cross-resource:child")
    parent.release()
    controller.close()
    registry.close()


def test_branch_server_uses_platform_capsule_claim_across_scope_generations() -> None:
    from tests.test_resource_scope_ownership_v1 import _scope_chain
    from noetrium_platform.foundation.governance.api import scope_key

    registry = make_model_admission_registry()
    authority = registry._test_authority
    controller = registry.controller_for(
        deployment_id="branch-capsule", deployment_generation="e" * 64,
        qualified_capacity=1, continuity_capacity=1,
    )
    parent = controller.try_reserve_continuity(owner_id="platform", flow_id="warm")
    assert parent is not None
    _study, _run, branch, _run_lease, branch_lease = _scope_chain(authority)
    branch_generation, branch_lease_id = authority.scope_ownership_cut(
        branch, scope_lease=branch_lease,
    )
    child_key = "minecraft-server:branch"
    child = resource_claim(
        claim_id="branch:server", resource_key=child_key,
        holder_key=scope_key(branch),
        generation=authority.ensure_generation(child_key).generation,
        owner_scope=branch,
        scope_generation=branch_generation.generation,
        scope_lease_id=branch_lease_id, owner_lease_id=None,
        attributes={"kind": "minecraft-server",
                    "parent_claim_id": parent.claim_id,
                    "parent_resource_key": controller._continuity_resource_key},
    )
    authorized = authority.admit_bundle(((child,),))
    assert claim_field(authorized[0], "claim_id") == "branch:server"
    with pytest.raises(ResourceClaimConflict, match="active child"):
        parent.release()
    authority.release_claim("branch:server")
    parent.release()
    controller.close()
    registry.close()


def test_atomic_cold_bundle_admits_parent_before_cross_resource_child() -> None:
    from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, scope_key
    from tests.test_resource_scope_ownership_v1 import _scope_chain

    registry = make_model_admission_registry()
    authority = registry._test_authority
    owner = registry._test_owner_lease
    parent_key = "capsule:cold"
    child_key = "server:cold"
    parent_generation = authority.ensure_generation(parent_key).generation
    child_generation = authority.ensure_generation(child_key).generation
    _experiment, _run, branch, _run_lease, branch_lease = _scope_chain(authority)
    branch_generation, branch_lease_id = authority.scope_ownership_cut(
        branch, scope_lease=branch_lease,
    )
    parent_id = "claim:cold-capsule"
    parent = resource_claim(
        claim_id=parent_id, resource_key=parent_key,
        holder_key=scope_key(PLATFORM_SCOPE), generation=parent_generation,
        owner_scope=PLATFORM_SCOPE,
        scope_generation=authority.ensure_scope_generation(PLATFORM_SCOPE).generation,
        scope_lease_id=None, owner_lease_id=lease_field(owner, "lease_id"),
    )
    child = resource_claim(
        claim_id="claim:cold-server", resource_key=child_key,
        holder_key=scope_key(branch), generation=child_generation,
        owner_scope=branch, scope_generation=branch_generation.generation,
        scope_lease_id=branch_lease_id, owner_lease_id=None,
        attributes={"parent_claim_id": parent_id,
                    "parent_resource_key": parent_key},
    )
    assert authority.snapshot_for_resource_keys(
        frozenset({parent_key, child_key})
    ).claims == ()
    admitted = authority.admit_bundle(((parent,), (child,)))
    assert tuple(claim_field(row, "claim_id") for row in admitted) == (
        parent_id, "claim:cold-server",
    )
    with pytest.raises(ResourceClaimConflict, match="active child"):
        authority.release_claim(parent_id)
    authority.release_claim("claim:cold-server")
    authority.release_claim(parent_id)
    registry.close()


def test_cold_resource_topology_schedules_capsule_before_server() -> None:
    from noetrium_platform.infrastructure.resources.api.topology import (
        resource_node, resource_topology,
    )
    from noetrium_platform.infrastructure.resources.api.topology_index import (
        ResourceTopologyIndex,
    )

    topology = resource_topology(
        "capsule-server-cold",
        resources=(
            resource_node(
                "server", kind="minecraft-server",
                authority_key="server:branch", realization=True,
            ),
            resource_node(
                "capsule", kind="container",
                authority_key="container:shared", realization=True,
            ),
        ),
        requires=(("server", "capsule"),),
    )
    order = ResourceTopologyIndex(topology).acquire_order
    assert order.index("capsule") < order.index("server")


def test_deep_affine_claim_cleanup_is_iterative_and_child_first() -> None:
    from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
    from noetrium_platform.infrastructure.resources.authority import (
        UniversalResourceAuthority,
    )

    claims = []
    for index in range(192):
        attrs = {}
        if index:
            attrs["parent_claim_id"] = f"lineage:{index-1:03}"
        claims.append(resource_claim(
            claim_id=f"lineage:{index:03}",
            resource_key="shared-physical-capsule",
            holder_key=f"member:{index:03}",
            generation=1,
            owner_scope=PLATFORM_SCOPE,
            scope_generation=1,
            scope_lease_id=None,
            owner_lease_id=None,
            attributes=attrs,
        ))
    ordered = UniversalResourceAuthority._claim_release_order(tuple(claims))
    assert tuple(claim_field(row, "claim_id") for row in ordered) == tuple(
        f"lineage:{index:03}" for index in range(191, -1, -1)
    )
    reverse = UniversalResourceAuthority._claim_release_order(tuple(reversed(claims)))
    assert tuple(claim_field(row, "claim_id") for row in reverse) == tuple(
        f"lineage:{index:03}" for index in range(191, -1, -1)
    )
