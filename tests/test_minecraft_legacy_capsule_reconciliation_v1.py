from __future__ import annotations

import unittest

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftCapsule,
)


def _claim(
    claim_id: str,
    *,
    resource_key: str,
    kind: str,
    runtime_identity: str,
    parent_claim_id: str | None = None,
) -> NoetriumUnit:
    return NoetriumUnit(
        unit_id="test-claim:" + claim_id,
        schemas=("resource.claim",),
        attributes={
            "kind": "resource.claim",
            "claim_id": claim_id,
            "resource_key": resource_key,
            "attributes": {
                "kind": kind,
                "runtime_identity_digest": runtime_identity,
                **({} if parent_claim_id is None else {"parent_claim_id": parent_claim_id}),
            },
        },
    )


class _Snapshot:
    def __init__(self, claims) -> None:
        self.claims = tuple(claims)


class _Authority:
    def __init__(self, claims, orphaned) -> None:
        self._snapshot = _Snapshot(claims)
        self._orphaned = tuple(orphaned)
        self.reconciled = []
        self.orphan_reconcile_calls = 0

    def snapshot(self):
        return self._snapshot

    def snapshot_for_claim_kinds(self, kinds):
        assert kinds == frozenset({"container", "minecraft-server"})
        return self._snapshot

    def orphaned_claim_groups(self):
        return self._orphaned

    def orphaned_claim_groups_for_claim_kinds(self, kinds):
        assert kinds == frozenset({"container", "minecraft-server"})
        return self._orphaned

    def reconcile(self, topology, **kwargs):
        self.reconciled.append((topology, kwargs))

    def reconcile_orphan_claims(self):
        self.orphan_reconcile_calls += 1
        return ()

    def reconcile_orphan_claims_for_claim_kinds(self, kinds):
        assert kinds == frozenset({"container"})
        return self.reconcile_orphan_claims()


class _Provider:
    provider_kind = "docker"


class MinecraftLegacyCapsuleReconciliationTests(unittest.TestCase):
    def test_only_unowned_legacy_runtime_identities_retire(self) -> None:
        current = "a" * 64
        live_legacy = "b" * 64
        orphan_legacy = "c" * 64
        unused_legacy = "d" * 64

        current_capsule = _claim(
            "container-current",
            resource_key="container:minecraft-capsule:current",
            kind="container",
            runtime_identity=current,
        )
        live_capsule = _claim(
            "container-live-legacy",
            resource_key="container:minecraft-capsule:live",
            kind="container",
            runtime_identity=live_legacy,
        )
        orphan_capsule = _claim(
            "container-orphan-legacy",
            resource_key="container:minecraft-capsule:orphan",
            kind="container",
            runtime_identity=orphan_legacy,
        )
        unused_capsule = _claim(
            "container-unused-legacy",
            resource_key="container:minecraft-capsule:unused",
            kind="container",
            runtime_identity=unused_legacy,
        )
        current_server = _claim(
            "server-current",
            resource_key="minecraft-branch:aaaaaaaaaaaaaaaaaaaaaaaa:server",
            kind="minecraft-server",
            runtime_identity=current,
        )
        live_legacy_server = _claim(
            "server-live-legacy",
            resource_key="minecraft-branch:bbbbbbbbbbbbbbbbbbbbbbbb:server",
            kind="minecraft-server",
            runtime_identity=live_legacy,
        )
        orphan_legacy_server = _claim(
            "server-orphan-legacy",
            resource_key="minecraft-branch:cccccccccccccccccccccccc:server",
            kind="minecraft-server",
            runtime_identity=orphan_legacy,
        )

        authority = _Authority(
            (
                current_capsule,
                live_capsule,
                orphan_capsule,
                unused_capsule,
                current_server,
                live_legacy_server,
                orphan_legacy_server,
            ),
            (("expired-scope", (orphan_legacy_server,)),),
        )
        capsule = object.__new__(_DockerMinecraftCapsule)
        capsule.authority = authority
        capsule.provider = _Provider()
        capsule.runtime_identity_digest = current

        retired = capsule.retire_inactive_legacy_capsules()

        self.assertEqual(
            retired,
            (
                "container:minecraft-capsule:orphan",
                "container:minecraft-capsule:unused",
            ),
        )
        self.assertEqual(len(authority.reconciled), 2)
        self.assertEqual(authority.orphan_reconcile_calls, 1)
        for _topology, kwargs in authority.reconciled:
            self.assertEqual(kwargs["desired_resource_ids"], frozenset())
            self.assertEqual(tuple(kwargs["providers"]), ("docker",))


    def test_distinct_child_runtime_identity_must_not_retire_live_parent(self) -> None:
        current = "a" * 64
        legacy_capsule_identity = "b" * 64
        world_server_identity = "c" * 64
        parent_id = "minecraft-capsule:708ae4b4" + "d" * 52
        parent = _claim(
            parent_id,
            resource_key="container:minecraft-capsule:live-with-server",
            kind="container", runtime_identity=legacy_capsule_identity,
        )
        child = _claim(
            "minecraft-server:active",
            resource_key="minecraft-branch:123456789012345678901234:server",
            kind="minecraft-server", runtime_identity=world_server_identity,
            parent_claim_id=parent_id,
        )
        retired_without_child = _claim(
            "minecraft-capsule:unused",
            resource_key="container:minecraft-capsule:unused",
            kind="container", runtime_identity="d" * 64,
        )
        authority = _Authority((parent, child, retired_without_child), ())
        capsule = object.__new__(_DockerMinecraftCapsule)
        capsule.authority = authority
        capsule.provider = _Provider()
        capsule.runtime_identity_digest = current
        retired = capsule.retire_inactive_legacy_capsules()
        self.assertEqual(retired, ("container:minecraft-capsule:unused",))
        self.assertEqual(len(authority.reconciled), 1)
        self.assertNotIn(parent_id, repr(authority.reconciled))

    def test_child_claim_remains_authoritative_even_if_lease_marked_orphan(self) -> None:
        parent_id = "minecraft-capsule:parent"
        parent = _claim(parent_id, resource_key="container:minecraft-capsule:parent",
                        kind="container", runtime_identity="b" * 64)
        child = _claim(
            "minecraft-server:pending-cleanup",
            resource_key="minecraft-branch:123456789012345678901234:server",
            kind="minecraft-server", runtime_identity="c" * 64,
            parent_claim_id=parent_id,
        )
        authority = _Authority((parent, child), (("expired", (child,)),))
        capsule = object.__new__(_DockerMinecraftCapsule)
        capsule.authority = authority
        capsule.provider = _Provider()
        capsule.runtime_identity_digest = "a" * 64
        self.assertEqual(capsule.retire_inactive_legacy_capsules(), ())
        self.assertEqual(authority.reconciled, [])


    def test_concurrent_child_admission_defers_only_proven_parent_retirement(self) -> None:
        from noetrium_platform.infrastructure.resources.authority.api.contracts import ResourceClaimConflict
        parent_id = "minecraft-capsule:race"
        parent = _claim(parent_id, resource_key="container:minecraft-capsule:race",
                        kind="container", runtime_identity="b" * 64)
        child = _claim("server:admitted", resource_key="minecraft-branch:race:server",
                       kind="minecraft-server", runtime_identity="c" * 64,
                       parent_claim_id=parent_id)

        class _RacingAuthority(_Authority):
            def reconcile(self, topology, **kwargs):
                self._snapshot = _Snapshot((parent, child))
                raise ResourceClaimConflict("cannot release resource parent claim while active child remains: " + parent_id)

        authority = _RacingAuthority((parent,), ())
        capsule = object.__new__(_DockerMinecraftCapsule)
        capsule.authority = authority
        capsule.provider = _Provider()
        capsule.runtime_identity_digest = "a" * 64
        self.assertEqual(capsule.retire_inactive_legacy_capsules(), ())

        class _UnrelatedConflict(_Authority):
            def reconcile(self, topology, **kwargs):
                raise ResourceClaimConflict("unrelated capacity claim")

        unrelated = _UnrelatedConflict((parent,), ())
        capsule.authority = unrelated
        with self.assertRaisesRegex(ResourceClaimConflict, "unrelated"):
            capsule.retire_inactive_legacy_capsules()


if __name__ == "__main__":
    unittest.main()
