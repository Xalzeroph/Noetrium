from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import telemetry_backend
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.composition.runtime_observability import MetricRuntimeObserver
from noetrium_platform.composition.model_deployments import freeze_model_deployment_set
from noetrium_platform.capabilities.model.serving.api.qualified_deployment import RoleModelAssignment, RoleModelManifest
from noetrium_platform.infrastructure.lifecycle.launch_control import (
    ExactRuntimeController,
    OneClickRuntimeManager,
    RuntimeControlStore,
    ServerRuntimeAdapter,
    ServerRuntimeControlPlane,
)
from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLeaseBusy
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.reliability.recovery.execution.runtime.file_lock import FileLockedRecoveryExecutionFactory
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryStore

from test_server_runtime_control_v29 import CallRecorder, authorities, deployment, manifest, runtime_adapter


class RuntimeMetricEmissionV81Tests(unittest.TestCase):
    def build(self, root: Path):
        d1=deployment("d1","GPU-1")
        d2=deployment("d2","GPU-2")
        roles=RoleModelManifest((RoleModelAssignment("planner","d1"),RoleModelAssignment("meta","d2")))
        ds=freeze_model_deployment_set(roles,(d1,d2))
        metrics=TelemetryStore(build_default_registry(), telemetry_backend(self, root/"metrics.sqlite3"))
        recorder=CallRecorder()
        adapter,_provider=runtime_adapter(authorities(recorder),ds,root)
        runtime_store=make_runtime_control_store(root/"runtime.json")
        controller=ExactRuntimeController(runtime_store,adapter)
        plane=ServerRuntimeControlPlane(controller,adapter)
        leases=recovery_lease_state(root/"lease.json")
        manager=OneClickRuntimeManager(
            plane,
            FileLockedRecoveryExecutionFactory(leases, lock_path=root/'recovery.execution.lock'),
            runtime_store,
        )
        ctx=ExecutionContext(run_id="run81",trace_id="tr81",span_id="sp81",component_id="runtime_manager")
        return manager,leases,metrics,ctx,MetricRuntimeObserver(metrics,ctx),manifest(ds)

    def test_one_click_runtime_emits_action_reconcile_start_qualification_and_lease_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            manager,leases,metrics,ctx,observer,m=self.build(Path(td))
            report=manager.run_exact(m,control_id="ctl",owner_id="owner",observer=observer)
            self.assertTrue(report.history_verified)
            rows=metrics.query(run_id="run81",limit=500)
            names=[r["metric"] for r in rows]
            self.assertEqual(names.count("runtime.control.action.count"),14)
            self.assertEqual(names.count("runtime.control.action.latency"),14)
            self.assertEqual(names.count("runtime.control.reconcile"),2)
            self.assertEqual(names.count("runtime.control.exact_service_start"),1)
            self.assertEqual(names.count("runtime.control.qualification"),1)
            self.assertEqual(names.count("resource.lease.wait"),1)
            self.assertIsNone(leases.read())

    def test_recovery_lease_conflict_is_observable_and_does_not_run_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            manager,leases,metrics,ctx,observer,m=self.build(Path(td))
            leases.acquire("other",m.digest(),ttl_seconds=300)
            with self.assertRaises(RecoveryLeaseBusy):
                manager.run_exact(m,control_id="ctl",owner_id="owner",observer=observer)
            rows=metrics.query(run_id="run81",limit=100)
            names=[r["metric"] for r in rows]
            self.assertIn("runtime.recovery.lease.conflicts",names)
            self.assertIn("resource.lease.wait",names)
            self.assertNotIn("runtime.control.action.count",names)


if __name__=="__main__": unittest.main()
