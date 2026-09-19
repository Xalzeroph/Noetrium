from __future__ import annotations

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from runtime_manager_test_support import make_runtime_control_store
from service_os_test_support import make_service_supervisor, ready_evidence

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.evidence.observability.status.runtime import PlatformStatusService
from noetrium_platform.infrastructure.reliability.diagnostics.runtime.status_projection import ForensicStatusProbe
from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeControlStore
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.reliability.recovery.composition import compose_recovery_lease_status_probe
from noetrium_platform.infrastructure.lifecycle.launch_control.status_readers import RuntimeControlStatusReader
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_transaction_status import RuntimeTransactionStatusProbe
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceSupervisor,
    PreparedServiceStartReconcileResult,
    PreparedServiceStartStatus,
    ServiceStartRecoveryHandle,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.status_reader import ServiceOperationalStatusReader
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.status_projection import ServiceOperationalStatusProbe


def h(v): return hashlib.sha256(v.encode()).hexdigest()

def contract():
    return ServiceLaunchContract('svc','g','/bin/echo',('/bin/echo','x'),'/tmp',h('env'),h('artifact'),h('runtime'),1,1,1)

class Crash(RuntimeError): pass

class Durable:
    start_recovery_durability='crash_durable'
    def reconcile(self,state,launch): return (None,())
    def start(self,launch): raise AssertionError
    def wait_ready(self,process,launch): return ready_evidence(process,launch,"ready","out","err")
    def stop(self,process,launch): return ()
    def prepare_start_recovery(self,launch,*,intent_id,attempt):
        return ServiceStartRecoveryHandle.from_payload('provider.v1',b'secret-provider-token')
    def start_prepared(self,launch,handle): raise Crash('after external start')
    def reconcile_prepared_start(self,launch,handle):
        return PreparedServiceStartReconcileResult(PreparedServiceStartStatus.UNKNOWN,None,(),"unknown")

class ServiceStartIntentStatusTests(unittest.TestCase):
    def test_prepared_start_crash_is_visible_as_operational_degradation_with_redacted_recovery_identity(self):
        with TemporaryDirectory() as td:
            root=Path(td); service_store=FileServiceStateStore(root/'svc.json')
            with self.assertRaises(Crash): make_service_supervisor(service_store,Durable()).start_exact(contract())
            runtime=make_runtime_control_store(root/'runtime.json'); runtime.create('ctl','manifest')
            forensics=ForensicStore(root/'forensics')
            try:
                status=PlatformStatusService((
                    RuntimeTransactionStatusProbe(RuntimeControlStatusReader(runtime.state_store, runtime.history)),
                    compose_recovery_lease_status_probe(recovery_lease_state(root/'lease.json')),
                    ServiceOperationalStatusProbe('svc', ServiceOperationalStatusReader(service_store, DirectoryServiceStartIntentStore(Path(service_store.reference()).with_name(Path(service_store.reference()).name + ".start-intents")))),
                    ForensicStatusProbe(ForensicDiagnosticEvidence(forensics)),
                )).snapshot().to_dict()
                svc=next(x for x in status['subsystems'] if x['subsystem']=='service:svc')
                self.assertEqual(svc['state'],'degraded_operational')
                self.assertIn('start_intent=prepared',svc['summary'])
                joined=' '.join(svc['evidence'])
                self.assertIn('service-start-recovery:provider.v1:',joined)
                self.assertNotIn('secret-provider-token',joined)
                self.assertIn('do not issue a second start', ' '.join(svc['next_commands']))
            finally: forensics.close()

    def test_exited_service_is_not_reported_ready(self):
        from noetrium_platform.infrastructure.lifecycle.service.runtime import ServicePhase
        from noetrium_platform.infrastructure.lifecycle.service.runtime.service_state_contracts import ServiceSupervisorState
        import time
        with TemporaryDirectory() as td:
            root=Path(td); service_store=FileServiceStateStore(root/'svc.json')
            service_store.write(ServiceSupervisorState('svc','contract',ServicePhase.EXITED,1,None,None,None,None,None,None,None,time.time()))
            runtime=make_runtime_control_store(root/'runtime.json'); runtime.create('ctl','manifest')
            forensics=ForensicStore(root/'forensics')
            try:
                data=PlatformStatusService((RuntimeTransactionStatusProbe(RuntimeControlStatusReader(runtime.state_store, runtime.history)),compose_recovery_lease_status_probe(recovery_lease_state(root/'l')),ServiceOperationalStatusProbe('svc',ServiceOperationalStatusReader(service_store, DirectoryServiceStartIntentStore(Path(service_store.reference()).with_name(Path(service_store.reference()).name + ".start-intents")))),ForensicStatusProbe(ForensicDiagnosticEvidence(forensics)))).snapshot().to_dict()
                self.assertEqual(next(x for x in data['subsystems'] if x['subsystem']=='service:svc')['state'],'failed')
            finally: forensics.close()

if __name__=='__main__': unittest.main()
