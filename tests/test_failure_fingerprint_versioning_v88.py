from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG

from noetrium_platform.infrastructure.reliability.failure.api import fingerprint_failure, failure_document, failure_field, replace_failure
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
        b=replace_failure(a,taxonomy_spec_sha256="f"*64)
        # Rebuild through primitive identity semantics for the ID check.
        from noetrium_platform.infrastructure.reliability.failure.api import build_failure
        b2=build_failure(
            component_id=failure_field(a,"component_id"),failure_domain=failure_field(a,"failure_domain"),failure_code=failure_field(a,"failure_code"),stage=failure_field(a,"stage"),
            context=failure_field(a,"context"),exc=RuntimeError("CUDA OOM 12345"),taxonomy_spec_sha256="f"*64,
            recommended_recovery=failure_field(a,"recommended_recovery"),
        )
        self.assertNotEqual(failure_field(a,"failure_id"),failure_field(b2,"failure_id"))
        fa=fingerprint_failure(failure_document(a)); fb=fingerprint_failure(failure_document(b))
        self.assertNotEqual(fa.fingerprint,fb.fingerprint)
        self.assertEqual(fa.family_fingerprint,fb.family_fingerprint)

    def test_incident_index_tracks_exact_and_cross_version_family_counts(self):
        a=self.base(); b=replace_failure(a,failure_id="failure_other",taxonomy_spec_sha256="e"*64)
        with tempfile.TemporaryDirectory() as td:
            idx=IncidentPatternIndex(Path(td)/"incident.sqlite3")
            pa=idx.observe(fingerprint_failure(failure_document(a)),failure_field(a,"failure_id"),timestamp=1.0)
            pb=idx.observe(fingerprint_failure(failure_document(b)),failure_field(b,"failure_id"),timestamp=2.0)
            self.assertEqual(pa.count,1)
            self.assertEqual(pb.count,1)
            self.assertEqual(pb.family_count,2)
            self.assertIn(failure_field(a,"failure_id"),pb.family_example_failure_ids)

if __name__=="__main__": unittest.main()
