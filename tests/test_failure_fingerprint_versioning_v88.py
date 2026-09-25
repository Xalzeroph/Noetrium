from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG

from noetrium_platform.infrastructure.reliability.failure.api import fingerprint_failure
from noetrium_platform.infrastructure.reliability.failure.api import build_failure_from_spec
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.reliability.forensics.composition.incident_index import IncidentPatternIndex


class FailureFingerprintVersioningV88Tests(unittest.TestCase):
    def base(self):
        spec=DEFAULT_FAILURE_CATALOG.require("MODEL_SERVING","MODEL_SERVICE_OOM","service_process_exit")
        return build_failure_from_spec(
            spec=spec,component_id="model",context=ExecutionContext("run","trace","span"),exc=RuntimeError("CUDA OOM 12345"),
        )

    def test_failure_id_and_exact_fingerprint_change_when_taxonomy_version_changes(self):
        a=self.base()
        b=replace(a,taxonomy_spec_sha256="f"*64)
        # Rebuild through primitive identity semantics for the ID check.
        from noetrium_platform.infrastructure.reliability.failure.api import build_failure
        b2=build_failure(
            component_id=a.component_id,failure_domain=a.failure_domain,failure_code=a.failure_code,stage=a.stage,
            context=a.context,exc=RuntimeError("CUDA OOM 12345"),taxonomy_spec_sha256="f"*64,
            recommended_recovery=a.recommended_recovery,
        )
        self.assertNotEqual(a.failure_id,b2.failure_id)
        fa=fingerprint_failure(a.to_dict()); fb=fingerprint_failure(b.to_dict())
        self.assertNotEqual(fa.fingerprint,fb.fingerprint)
        self.assertEqual(fa.family_fingerprint,fb.family_fingerprint)

    def test_incident_index_tracks_exact_and_cross_version_family_counts(self):
        a=self.base(); b=replace(a,failure_id="failure_other",taxonomy_spec_sha256="e"*64)
        with tempfile.TemporaryDirectory() as td:
            idx=IncidentPatternIndex(Path(td)/"incident.sqlite3")
            pa=idx.observe(fingerprint_failure(a.to_dict()),a.failure_id,timestamp=1.0)
            pb=idx.observe(fingerprint_failure(b.to_dict()),b.failure_id,timestamp=2.0)
            self.assertEqual(pa.count,1)
            self.assertEqual(pb.count,1)
            self.assertEqual(pb.family_count,2)
            self.assertIn(a.failure_id,pb.family_example_failure_ids)

if __name__=="__main__": unittest.main()
