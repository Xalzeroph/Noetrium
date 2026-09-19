from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG
from noetrium_platform.infrastructure.reliability.forensics.runtime import CrashBundleBuilder
from noetrium_platform.infrastructure.reliability.failure.api import build_failure_from_spec
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class CrashBundleTaxonomyV89Tests(unittest.TestCase):
    def test_bundle_is_self_describing_for_taxonomy_and_incident_family(self):
        spec=DEFAULT_FAILURE_CATALOG.require("METHOD","OBSERVATION_DELIVERY","post_commit_observability")
        failure=build_failure_from_spec(
            spec=spec,component_id="method",context=ExecutionContext("run","trace","span"),exc=RuntimeError("sink down"),
        )
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with ForensicStore(root/"forensics") as store:
                store.append_failure(failure)
                out=root/"bundle.json"
                manifest=CrashBundleBuilder(store).publish(failure.failure_id,out)
            data=json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest.schema_version,2)
            self.assertTrue(data["taxonomy"]["registered"])
            self.assertFalse(data["taxonomy"]["semantic_drift"])
            self.assertEqual(data["taxonomy"]["current_spec_digest"],spec.digest())
            self.assertEqual(len(data["fingerprints"]["exact"]),64)
            self.assertEqual(len(data["fingerprints"]["family"]),64)
            self.assertNotEqual(data["fingerprints"]["exact"],data["fingerprints"]["family"])

if __name__=="__main__": unittest.main()
