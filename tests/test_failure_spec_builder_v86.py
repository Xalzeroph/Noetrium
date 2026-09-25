from __future__ import annotations

from pathlib import Path
import unittest

from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG
from noetrium_platform.infrastructure.reliability.forensics.runtime import FailureCatalogSourceAudit
from noetrium_platform.infrastructure.reliability.failure.api import build_failure_from_spec
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class FailureSpecBuilderV86Tests(unittest.TestCase):
    def test_builder_takes_semantics_only_from_spec(self):
        spec=DEFAULT_FAILURE_CATALOG.require("MODEL_SERVING","MODEL_SERVICE_OOM","service_process_exit")
        f=build_failure_from_spec(
            spec=spec, component_id="model.planner",
            context=ExecutionContext("run","trace","span"), exc=RuntimeError("oom"),
        )
        self.assertEqual((f.failure_domain,f.failure_code,f.stage),spec.key)
        self.assertEqual(f.recommended_recovery,spec.default_recovery)
        self.assertEqual(f.comparability_risk,spec.comparability_risk)

    def test_production_source_has_no_free_form_failure_builder_bypass(self):
        root=Path(__file__).resolve().parents[1]/"noetrium_platform"
        report=FailureCatalogSourceAudit(root,DEFAULT_FAILURE_CATALOG).run()
        self.assertEqual(report.free_form_builder_calls,())
        self.assertEqual(report.errors,())


if __name__=="__main__": unittest.main()
