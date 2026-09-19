from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.composition.release_quiescence import (
    PersistentSessionReleaseConsumerProbe,
    RecoveryLeaseReleaseConsumerProbe,
)
from noetrium_platform.foundation.governance.release.composition.retirement import ReleaseQuiescenceVerifier
from noetrium_platform.foundation.governance.release.api import ActiveReleasePin, ReleaseConsumerQuiescence
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.lifecycle.session.runtime.status import PersistentSessionObservation, PersistentSessionObservationState


class SessionProbe:
    def __init__(self, state): self.state = state
    def observe(self):
        return PersistentSessionObservation(
            'runtime-ctl', self.state, self.state.value, evidence_refs=('tmux:evidence',)
        )


class ServiceConsumerProbe:
    consumer_id = 'service:svc'
    def __init__(self, quiescent=True): self.quiescent = quiescent
    def observe(self, pin):
        del pin
        return ReleaseConsumerQuiescence(
            self.consumer_id,
            self.quiescent,
            'stopped' if self.quiescent else 'live',
            ('service:evidence',),
        )


class ServerReleaseQuiescenceV165Tests(unittest.TestCase):
    def pin(self): return ActiveReleasePin('ctl', 'a'*64, 'b'*64, 1.0)

    def verifier(self, root, *, session=PersistentSessionObservationState.MISSING, service=True):
        lease = recovery_lease_state(Path(root)/'lease.json')
        verifier = ReleaseQuiescenceVerifier((
            PersistentSessionReleaseConsumerProbe(SessionProbe(session)),
            RecoveryLeaseReleaseConsumerProbe(lease),
            ServiceConsumerProbe(service),
        ))
        return verifier, lease

    def test_only_proven_missing_controller_and_quiescent_services_are_safe(self):
        with TemporaryDirectory() as td:
            verifier, _ = self.verifier(td)
            proof = verifier.prove(self.pin())
            self.assertTrue(proof.quiescent)
            self.assertEqual(proof.blockers, ())

    def test_unknown_or_drifted_tmux_is_not_treated_as_absent(self):
        with TemporaryDirectory() as td:
            for state in (
                PersistentSessionObservationState.EXACT,
                PersistentSessionObservationState.UNAVAILABLE,
                PersistentSessionObservationState.DRIFT,
                PersistentSessionObservationState.UNBOUND,
            ):
                with self.subTest(state=state):
                    verifier, _ = self.verifier(td, session=state)
                    self.assertFalse(verifier.prove(self.pin()).quiescent)

    def test_live_service_blocks_retirement_even_when_tmux_is_missing(self):
        with TemporaryDirectory() as td:
            verifier, _ = self.verifier(td, service=False)
            proof = verifier.prove(self.pin())
            self.assertFalse(proof.quiescent)
            self.assertTrue(any('service:svc' in item for item in proof.blockers))

    def test_same_manifest_recovery_lease_blocks_retirement(self):
        with TemporaryDirectory() as td:
            verifier, lease = self.verifier(td)
            lease.acquire('operator', 'a'*64, ttl_seconds=100, now=1)
            proof = verifier.prove(self.pin())
            self.assertFalse(proof.quiescent)
            self.assertTrue(any('runtime-recovery-lease' in item for item in proof.blockers))

    def test_other_manifest_recovery_lease_does_not_pin_this_release(self):
        with TemporaryDirectory() as td:
            verifier, lease = self.verifier(td)
            lease.acquire('operator', 'c'*64, ttl_seconds=100, now=1)
            self.assertTrue(verifier.prove(self.pin()).quiescent)


if __name__ == '__main__': unittest.main()
