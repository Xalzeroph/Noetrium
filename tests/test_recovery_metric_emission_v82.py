from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import telemetry_backend
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.model.serving.api import RecoveryStep
from noetrium_platform.capabilities.model.serving.runtime import DurableExactRecoveryRunner
from noetrium_platform.composition.model_recovery_observability import MetricDurableRecoveryObserver
from noetrium_platform.capabilities.model.serving.providers.recovery_storage import FileDurableRecoveryStore
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryStore

from test_model_os_v11 import ModelOSV11Tests, _RecoveryExecutor


class RecoveryMetricEmissionV82Tests(unittest.TestCase):
    def test_interrupted_exact_restart_and_resume_emit_recovery_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            plan=ModelOSV11Tests()._plan()
            store=FileDurableRecoveryStore(root/"recovery.json", guard_path=root/"recovery.guard.lock")
            metrics=TelemetryStore(build_default_registry(), telemetry_backend(self, root/"metrics.sqlite3"))
            ctx=ExecutionContext(run_id="run82",trace_id="tr82",span_id="sp82",component_id="model_recovery")
            executor=_RecoveryExecutor(RecoveryStep.RESTART_EXACT_MODEL)
            runner=DurableExactRecoveryRunner(store,executor,observer=MetricDurableRecoveryObserver(metrics,ctx))

            with self.assertRaises(OSError):
                runner.run(plan,attempt_id="a82")
            self.assertEqual(store.load().current_effect_certainty,"unknown")

            executor.calls.clear()
            report=runner.run(plan,attempt_id="a82")
            self.assertEqual(executor.calls[0],RecoveryStep.RECONCILE_PROCESS)
            self.assertEqual(report.attempt.phase.value,"succeeded")

            rows=metrics.query(run_id="run82",limit=500)
            names=[row["metric"] for row in rows]
            self.assertEqual(names.count("recovery.attempts"),2)
            self.assertEqual(names.count("recovery.duration"),2)
            self.assertGreaterEqual(names.count("recovery.step.duration"),len(plan.steps))
            attempts=[row for row in rows if row["metric"]=="recovery.attempts"]
            results={row["dimensions"]["result"] for row in attempts}
            self.assertEqual(results,{"failed","success"})


if __name__=="__main__": unittest.main()
