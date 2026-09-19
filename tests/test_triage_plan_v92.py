from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG

from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.failure.api import build_failure_from_spec
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import TriagePlanService
from noetrium_platform.product.operator.runtime.parser import build_parser
from noetrium_platform.product.operator.query.runtime.route_diagnostics import route_diagnostics


class TriagePlanV92Tests(unittest.TestCase):
    def test_oom_plan_is_evidence_first_and_surfaces_missing_runtime_inputs(self):
        spec=DEFAULT_FAILURE_CATALOG.require("MODEL_SERVING","MODEL_SERVICE_OOM","service_process_exit")
        f=build_failure_from_spec(spec=spec,component_id="model",context=ExecutionContext("run","trace","span"),exc=RuntimeError("oom"))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with ForensicStore(root) as store:
                store.append_failure(f)
                plan=TriagePlanService(ForensicDiagnosticEvidence(store)).build(f.failure_id)
                self.assertEqual(tuple(x.check for x in plan.steps[:4]),("taxonomy","evidence_integrity","exact_location","joined_debug_snapshot"))
                self.assertEqual(plan.owner,"model_os")
                self.assertEqual(plan.recovery_action,"restart_exact_model")
                runtime=next(x for x in plan.steps if x.check=="runtime-status")
                self.assertEqual(runtime.required_inputs,("runtime_status_layout",))
                self.assertIsNone(runtime.command)

    def test_cli_route_builds_plan_without_executing_recovery(self):
        spec=DEFAULT_FAILURE_CATALOG.require("STATE","VERSION_CONFLICT","commit")
        f=build_failure_from_spec(spec=spec,component_id="state",context=ExecutionContext("r","t","s"),exc=RuntimeError("conflict"))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with ForensicStore(root) as store: store.append_failure(f)
            args=build_parser().parse_args(["triage-plan",str(root),f.failure_id])
            plan=route_diagnostics(args)
            self.assertEqual(plan.recovery_action,"manual_diagnosis")
            self.assertTrue(any(x.check=="last-writer" for x in plan.steps))

if __name__=="__main__": unittest.main()
