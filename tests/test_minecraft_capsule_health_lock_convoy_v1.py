from __future__ import annotations

from threading import Event, RLock, Thread
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


class MinecraftCapsuleHealthLockConvoyTests(unittest.TestCase):
    def test_slow_health_observation_does_not_hold_capsule_metadata_lock(self) -> None:
        capsule = object.__new__(_DockerMinecraftCapsule)
        capsule.lock = RLock()
        capsule._ticket = None
        entered = Event()
        release = Event()

        ticket = realization_ticket(
            ticket_id="ticket-a",
            effect_id="effect-a",
            realization_key="realization-a",
            resource_key="capsule-a",
            provider_kind="docker",
            generation=1,
            spec_digest="a" * 64,
            holder_key="holder-a",
        )
        observation = resource_observation(
            resource_key="capsule-a",
            generation=1,
            ticket_id="ticket-a",
            spec_digest="a" * 64,
            exists=True,
            ready=True,
            physical=physical_identity("docker", "capsule-container-a"),
        )

        def slow_current(self):
            entered.set()
            if not release.wait(3.0):
                raise TimeoutError("fixture did not release slow health observation")
            return ticket, observation

        capsule._current = types.MethodType(slow_current, capsule)
        capsule._authority_ticket = types.MethodType(lambda self: ticket, capsule)
        outcome: list[BaseException | None] = []

        def check() -> None:
            try:
                capsule.assert_healthy()
            except BaseException as exc:
                outcome.append(exc)
            else:
                outcome.append(None)

        thread = Thread(target=check, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(1.0))

        acquired = capsule.lock.acquire(timeout=0.2)
        if acquired:
            capsule.lock.release()

        release.set()
        thread.join(3.0)

        self.assertTrue(
            acquired,
            "slow capsule Authority observation held the capsule metadata lock",
        )
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [None])
        self.assertIs(capsule._ticket, ticket)


if __name__ == "__main__":
    unittest.main()
