from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.evidence.observability.status.runtime import PlatformStatusService
from noetrium_platform.research.execution.api import DeploymentStatusIdentity
from noetrium_platform.infrastructure.reliability.diagnostics.runtime.status_projection import ForensicStatusProbe
from noetrium_platform.research.execution.runtime.manager.heartbeat_storage import FileServiceHeartbeatStore
from noetrium_platform.research.execution.runtime.manager import RuntimeControlStore, RuntimeTxnPhase
from noetrium_platform.research.execution.runtime.manager.heartbeat import ServiceHeartbeat
from noetrium_platform.infrastructure.reliability.recovery.providers.lease_store import RecoveryLeaseStore
from noetrium_platform.infrastructure.reliability.recovery.composition import compose_recovery_lease_status_probe
from noetrium_platform.research.execution.runtime.manager.status_readers import RuntimeControlStatusReader, ServiceHeartbeatStatusReader
from noetrium_platform.research.execution.runtime.manager.model_deployment_status import ModelDeploymentStatusProbe
from noetrium_platform.research.execution.runtime.manager.runtime_transaction_status import RuntimeTransactionStatusProbe
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import ServicePhase
from noetrium_platform.infrastructure.lifecycle.service.runtime.service_state_contracts import ServiceSupervisorState
from noetrium_platform.infrastructure.lifecycle.service.runtime.status_reader import ServiceOperationalStatusReader
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.status_projection import ServiceOperationalStatusProbe

from test_server_runtime_control_v29 import deployment


class JoinedRuntimeStatusV78Tests(unittest.TestCase):
    def build(self, root: Path, *, heartbeat_timestamp: float | None = None):
        d=deployment("planner","GPU-0")
        runtime=make_runtime_control_store(root/"runtime.json")
        state=runtime.create("ctl","manifest")
        runtime.write(replace(state,phase=RuntimeTxnPhase.SUCCEEDED))

        heartbeats=FileServiceHeartbeatStore(root/"heartbeats")
        heartbeats.write(ServiceHeartbeat(
            d.deployment_id,
            d.stack.digest(),
            123,
            "start:123",
            "argv",
            True,
            d.certificate.digest(),
            time.time() if heartbeat_timestamp is None else heartbeat_timestamp,
        ))

        service_store=FileServiceStateStore(root/"service.json")
        service_store.write(ServiceSupervisorState(
            d.deployment_id,
            "contract",
            ServicePhase.RUNNING,
            1,
            None,
            "ready://planner",
            "capture://stdout",
            "capture://stderr",
            time.time(),
            None,
            None,
            time.time(),
            time.time(),
        ))
        lease=RecoveryLeaseStore(root/"recovery_lease.json")
        forensics=ForensicStore(root/"forensics")
        heartbeat_reader=ServiceHeartbeatStatusReader(heartbeats)
        service=PlatformStatusService((
            RuntimeTransactionStatusProbe(RuntimeControlStatusReader(runtime.state_store, runtime.history)),
            compose_recovery_lease_status_probe(lease),
            ModelDeploymentStatusProbe(
                DeploymentStatusIdentity(d.deployment_id,d.stack.digest(),d.certificate.digest()),
                heartbeat_reader,
                heartbeat_max_age_seconds=30.0,
            ),
            ServiceOperationalStatusProbe(d.deployment_id, ServiceOperationalStatusReader(service_store, DirectoryServiceStartIntentStore(Path(service_store.reference()).with_name(Path(service_store.reference()).name + ".start-intents")))),
            ForensicStatusProbe(ForensicDiagnosticEvidence(forensics)),
        ))
        return service,forensics

    def test_one_joined_snapshot_reports_runtime_model_service_forensics(self):
        with tempfile.TemporaryDirectory() as td:
            service,forensics=self.build(Path(td))
            try:
                status=service.snapshot()
                data=status.to_dict()
                self.assertEqual(data["status"],"ready")
                names={x["subsystem"] for x in data["subsystems"]}
                self.assertTrue({"runtime","recovery_lease","model:planner","service:planner","forensics"} <= names)
            finally:
                forensics.close()

    def test_stale_model_heartbeat_is_immediately_visible_as_failed(self):
        with tempfile.TemporaryDirectory() as td:
            service,forensics=self.build(Path(td),heartbeat_timestamp=time.time()-120)
            try:
                data=service.snapshot().to_dict()
                self.assertEqual(data["status"],"failed")
                model=next(x for x in data["subsystems"] if x["subsystem"]=="model:planner")
                self.assertIn("stale_heartbeat",model["summary"])
                self.assertEqual(model["reason_codes"],["stale_heartbeat"])
            finally:
                forensics.close()

    def test_stale_disposable_projection_is_degraded_evidence_not_scientific_failure(self):
        with tempfile.TemporaryDirectory() as td:
            service,forensics=self.build(Path(td))
            try:
                forensics.index.set_freshness("events",1,"1"*64)
                data=service.snapshot().to_dict()
                self.assertEqual(data["status"],"degraded_evidence")
                f=next(x for x in data["subsystems"] if x["subsystem"]=="forensics")
                self.assertEqual(f["state"],"degraded_evidence")
                self.assertIn("projection stale",f["summary"])
                self.assertEqual(f["reason_codes"],["forensic_projection_stale"])
            finally:
                forensics.close()


if __name__=="__main__": unittest.main()
