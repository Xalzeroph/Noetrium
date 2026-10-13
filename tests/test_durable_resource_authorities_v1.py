from __future__ import annotations

from resource_test_support import build_test_platform_meta

import pytest

from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentProfileMaterialization,
    EnvironmentProfileRevision,
)
from noetrium_platform.composition.platform_meta import build_platform_meta
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import resource_claim, claim_field, lease_field
from noetrium_platform.infrastructure.resources.compute.api import ComputeGPU, ComputeHost


def test_universal_authority_survives_platform_meta_rebuild(tmp_path) -> None:
    first = build_test_platform_meta(tmp_path)
    generation = first.resource_authority.ensure_generation("resource:a")
    claim_request = resource_claim(
        "claim:a",
        "resource:a",
        "holder:a",
        generation.generation,
        owner_scope=PLATFORM_SCOPE,
        scope_generation=1,
        scope_lease_id=None,
        owner_lease_id=None,
        attributes={"kind": "test"},
    )
    claim = first.resource_authority.acquire_claim(claim_request)
    lease = first.resource_authority.acquire_ttl_lease(
        lease_id="lease:a",
        resource_key="resource:a",
        holder_key="holder:a",
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=120.0,
        metadata={"kind": "test"},
    )

    second = build_test_platform_meta(tmp_path)
    snapshot = second.resource_authority.snapshot()
    assert snapshot.generation_for("resource:a").generation == generation.generation
    assert snapshot.current_claims_for("resource:a") == (claim,)
    restored = second.resource_authority.get_lease("lease:a")
    assert lease_field(restored, "resource_key") == lease_field(lease, "resource_key")
    assert lease_field(restored, "generation") == lease_field(lease, "generation")
    assert not lease_field(restored, "released")


def test_compute_inventory_is_restart_safe_fact_catalog(tmp_path) -> None:
    first = build_test_platform_meta(tmp_path)
    host = ComputeHost(
        "node-a",
        PLATFORM_SCOPE,
        64,
        256 * 1024**3,
        (ComputeGPU("GPU-a", 48 * 1024**3, "RTX 4090"),),
        labels=(("pool", "local"),),
    )
    first.compute_inventory.register_host(host)

    second = build_test_platform_meta(tmp_path)
    assert second.compute_inventory.host("node-a") == host
    assert second.compute_inventory.list_hosts(scope=PLATFORM_SCOPE) == (host,)
    # Inventory is durable fact state, while lifecycle truth is still only the
    # Universal Authority state machine.
    assert first.resource_authority.path == first.compute_inventory.path
    assert second.resource_authority.path == second.compute_inventory.path


def test_environment_profile_materialization_survives_rebuild_without_lease_authority(tmp_path) -> None:
    revision = EnvironmentProfileRevision(
        "minecraft.local",
        "minecraft",
        "1" * 64,
    )
    materialization = EnvironmentProfileMaterialization(
        profile_id=revision.profile_id,
        profile_revision=revision.profile_revision,
        build_input_digest="2" * 64,
        runtime_identity_digest="3" * 64,
        deployment_receipt_digest="4" * 64,
        runtime_reference="noetrium-env-minecraft:live-main",
    )
    first = build_test_platform_meta(tmp_path)
    first.environments.register_profile_revision(revision)
    first.environments.register_profile_materialization(materialization)

    second = build_test_platform_meta(tmp_path)
    assert second.environments.profile_revision(
        revision.profile_id,
        revision.profile_revision,
    ) == revision
    assert second.environments.profile_materialization(
        materialization.materialization_digest
    ) == materialization


def test_compute_inventory_refreshes_observed_facts_for_stable_host_identity(
    tmp_path,
) -> None:
    meta = build_test_platform_meta(tmp_path)
    original = ComputeHost(
        "node-a",
        PLATFORM_SCOPE,
        64,
        256 * 1024**3,
        (
            ComputeGPU(
                "GPU-a",
                48 * 1024**3,
                "RTX 4090",
                labels=(("runtime_index", "0"),),
            ),
        ),
        labels=(("discovery", "local-auto"),),
    )
    meta.compute_inventory.register_host(original)

    refreshed = ComputeHost(
        "node-a",
        PLATFORM_SCOPE,
        56,
        240 * 1024**3,
        (
            ComputeGPU(
                "GPU-a",
                48 * 1024**3,
                "RTX 4090",
                labels=(
                    ("runtime_index", "0"),
                    ("pci_bus_id", "0000:01:00.0"),
                    ("numa_node", "0"),
                ),
            ),
        ),
        labels=(("discovery", "local-auto"),),
    )
    meta.compute_inventory.register_host(refreshed)
    assert meta.compute_inventory.host("node-a") == refreshed


def test_compute_inventory_refresh_fails_closed_on_scope_or_gpu_identity_drift(
    tmp_path,
) -> None:
    meta = build_test_platform_meta(tmp_path)
    first = ComputeHost(
        "node-a",
        PLATFORM_SCOPE,
        8,
        1024,
        (ComputeGPU("GPU-a", 1024),),
    )
    meta.compute_inventory.register_host(first)
    meta.compute_inventory.register_host(
        ComputeHost(
            "node-b",
            PLATFORM_SCOPE,
            8,
            1024,
            (ComputeGPU("GPU-b", 1024),),
        )
    )

    from noetrium_platform.foundation.scope.api import ScopeKind, scope_unit

    with pytest.raises(ValueError, match="scope drifted"):
        meta.compute_inventory.register_host(
            ComputeHost(
                "node-a",
                scope_unit(ScopeKind.PROJECT, "other"),
                8,
                1024,
                (ComputeGPU("GPU-a", 1024),),
            )
        )

    with pytest.raises(ValueError, match="multiple compute hosts"):
        meta.compute_inventory.register_host(
            ComputeHost(
                "node-a",
                PLATFORM_SCOPE,
                8,
                1024,
                (ComputeGPU("GPU-b", 1024),),
            )
        )
