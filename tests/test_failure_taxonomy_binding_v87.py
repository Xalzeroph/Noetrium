from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.failure.api import build_failure_from_spec
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import FailureDiagnosisService


class FailureTaxonomyBindingV87Tests(unittest.TestCase):
    def test_spec_driven_failure_binds_exact_spec_digest(self):
        spec=DEFAULT_FAILURE_CATALOG.require("MODEL_SERVING","MODEL_SERVICE_OOM","service_process_exit")
        f=build_failure_from_spec(
            spec=spec, component_id="model",
            context=ExecutionContext("run","trace","span"), exc=RuntimeError("oom"),
        )
        self.assertEqual(f.taxonomy_spec_sha256,spec.digest())

    def test_diagnosis_detects_historical_semantic_drift(self):
        spec=DEFAULT_FAILURE_CATALOG.require("MODEL_SERVING","MODEL_SERVICE_OOM","service_process_exit")
        f=build_failure_from_spec(
            spec=spec, component_id="model",
            context=ExecutionContext("run","trace","span"), exc=RuntimeError("oom"),
        )
        historical=replace(f,taxonomy_spec_sha256="0"*64)
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                store.append_failure(historical)
                diag=FailureDiagnosisService(ForensicDiagnosticEvidence(store)).why(historical.failure_id)
                self.assertTrue(diag.taxonomy["registered"])
                self.assertTrue(diag.taxonomy["semantic_drift"])
                self.assertEqual(diag.taxonomy["current_spec_digest"],spec.digest())

    def test_current_bound_failure_reports_no_drift(self):
        spec=DEFAULT_FAILURE_CATALOG.require("METHOD","OBSERVATION_DELIVERY","post_commit_observability")
        f=build_failure_from_spec(
            spec=spec, component_id="method",
            context=ExecutionContext("run","trace","span"), exc=RuntimeError("sink"),
        )
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                store.append_failure(f)
                diag=FailureDiagnosisService(ForensicDiagnosticEvidence(store)).why(f.failure_id)
                self.assertFalse(diag.taxonomy["semantic_drift"])

if __name__=="__main__": unittest.main()
