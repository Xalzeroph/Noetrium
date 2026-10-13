from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import types
import unittest

from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftCapsule,
)
from noetrium_platform.infrastructure.resources.authority.api import (
    physical_identity,
    resource_observation,
    realization_ticket,
)


def _ticket_and_observation():
    ticket = realization_ticket(
        ticket_id="ticket-capsule",
        effect_id="effect-capsule",
        realization_key="realization-capsule",
        resource_key="container:minecraft-capsule:test",
        provider_kind="docker",
        generation=3,
        spec_digest="a" * 64,
        holder_key="platform:default",
    )
    observation = resource_observation(
        resource_key="container:minecraft-capsule:test",
        generation=3,
        ticket_id="ticket-capsule",
        spec_digest="a" * 64,
        exists=True,
        ready=True,
        physical=physical_identity("docker", "container-exact-id"),
    )
    return ticket, observation


def _capsule_fixture():
    capsule = object.__new__(_DockerMinecraftCapsule)
    capsule.lock = RLock()
    capsule._ticket = None
    capsule._physical_identity = None
    return capsule


class MinecraftCapsulePhysicalSnapshotTests(unittest.TestCase):
    def test_adopted_capsule_hot_path_does_not_reobserve_docker(self) -> None:
        capsule = _capsule_fixture()
        ticket, observation = _ticket_and_observation()
        physical_observations = 0

        def current(self):
            nonlocal physical_observations
            physical_observations += 1
            return ticket, observation

        capsule._current = types.MethodType(current, capsule)
        capsule._authority_ticket = types.MethodType(lambda self: ticket, capsule)

        self.assertTrue(capsule.attach_existing())
        self.assertEqual(physical_observations, 1)

        def use_hot_path(_index: int) -> str:
            for _ in range(32):
                capsule.assert_healthy()
                self.assertEqual(capsule.container_name, "container-exact-id")
            return capsule.container_name

        with ThreadPoolExecutor(max_workers=32) as pool:
            names = tuple(pool.map(use_hot_path, range(128)))

        self.assertEqual(set(names), {"container-exact-id"})
        self.assertEqual(
            physical_observations,
            1,
            "warm capsule hot path repeated Docker physical observation",
        )

    def test_close_invalidates_local_physical_snapshot(self) -> None:
        capsule = _capsule_fixture()
        ticket, observation = _ticket_and_observation()
        physical_observations = 0

        def current(self):
            nonlocal physical_observations
            physical_observations += 1
            return ticket, observation

        capsule._current = types.MethodType(current, capsule)
        capsule._authority_ticket = types.MethodType(lambda self: ticket, capsule)

        self.assertTrue(capsule.attach_existing())
        capsule.close()
        capsule.assert_healthy()

        self.assertEqual(physical_observations, 2)
        self.assertEqual(capsule.container_name, "container-exact-id")

    def test_authority_generation_drift_rejects_cached_identity(self) -> None:
        capsule = _capsule_fixture()
        ticket, observation = _ticket_and_observation()
        current_ticket = [ticket]
        physical_observations = 0

        def current(self):
            nonlocal physical_observations
            physical_observations += 1
            return ticket, observation

        capsule._current = types.MethodType(current, capsule)
        capsule._authority_ticket = types.MethodType(
            lambda self: current_ticket[0],
            capsule,
        )

        self.assertTrue(capsule.attach_existing())
        current_ticket[0] = realization_ticket(
            ticket_id="ticket-capsule-next",
            effect_id="effect-capsule-next",
            realization_key="realization-capsule-next",
            resource_key="container:minecraft-capsule:test",
            provider_kind="docker",
            generation=4,
            spec_digest="b" * 64,
            holder_key="platform:default",
        )

        with self.assertRaisesRegex(RuntimeError, "Authority generation drifted"):
            capsule.assert_healthy()
        self.assertEqual(physical_observations, 1)

    def test_authority_fence_reads_only_capsule_sparse_cut(self) -> None:
        capsule = _capsule_fixture()
        ticket, _observation = _ticket_and_observation()
        capsule.resource_key = "container:minecraft-capsule:test"
        seen = []

        class _Snapshot:
            def current_ticket_for(self, resource_key):
                self_resource = "container:minecraft-capsule:test"
                if resource_key != self_resource:
                    raise AssertionError(resource_key)
                return ticket

        class _Authority:
            def snapshot(self):
                raise AssertionError("global Authority snapshot used on capsule hot path")

            def snapshot_for_resource_keys(self, resource_keys):
                seen.append(resource_keys)
                return _Snapshot()

        capsule.authority = _Authority()
        self.assertIs(capsule._authority_ticket(), ticket)
        self.assertEqual(
            seen,
            [frozenset({"container:minecraft-capsule:test"})],
        )


if __name__ == "__main__":
    unittest.main()
