from __future__ import annotations

from noetrium_platform.foundation.governance.release.api import ReleaseQuiescenceProof
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.foundation.governance.release.runtime.active_pin_store import ActiveReleasePinStore
from noetrium_platform.foundation.governance.release.runtime.pin_retirement import ActiveReleasePinRetirer, ReleaseNotQuiescent


class Proofs:
    def __init__(self, blockers=()): self.blockers=tuple(blockers); self.calls=0
    def prove(self,pin):
        self.calls+=1
        return ReleaseQuiescenceProof.create(pin,blockers=self.blockers,evidence_refs=('proof:test',))


class ActiveReleaseRetirementV164Tests(unittest.TestCase):
    def test_pin_retires_only_with_exact_quiescence_proof(self):
        with TemporaryDirectory() as td:
            store=ActiveReleasePinStore(Path(td))
            store.acquire('ctl','a'*64,'b'*64)
            report=ActiveReleasePinRetirer(store,Proofs()).retire('ctl','a'*64)
            self.assertTrue(report.retired)
            self.assertTrue(report.proof.quiescent)
            self.assertIsNone(store.get('ctl','a'*64))

    def test_blocked_proof_preserves_pin(self):
        with TemporaryDirectory() as td:
            store=ActiveReleasePinStore(Path(td))
            store.acquire('ctl','a'*64,'b'*64)
            with self.assertRaises(ReleaseNotQuiescent):
                ActiveReleasePinRetirer(store,Proofs(('service still live',))).retire('ctl','a'*64)
            self.assertIsNotNone(store.get('ctl','a'*64))

if __name__=='__main__': unittest.main()
