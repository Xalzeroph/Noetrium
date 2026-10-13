from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceQuiescenceProbe,
    ExactServiceSupervisor,
    ServicePhase,
    ServiceSupervisorState,
)


def h(ch): return ch*64

def contract():
    return ServiceLaunchContract('svc','g','/bin/echo',('/bin/echo','x'),'/tmp',h('a'),h('b'),h('c'),10,10,1)


class Adapter:
    def __init__(self, live=None): self.live=live
    def reconcile(self,state,contract): return self.live,('proc:checked',)
    def start(self,contract): raise AssertionError('not used')
    def wait_ready(self,process,contract): raise AssertionError('not used')
    def stop(self,process,contract): raise AssertionError('not used')


class ServiceQuiescenceProbeV167Tests(unittest.TestCase):
    def test_missing_state_is_quiescent_when_no_start_intent_exists(self):
        with TemporaryDirectory() as td:
            sup=make_service_supervisor(FileServiceStateStore(Path(td)/'state.json'),Adapter())
            self.assertTrue(ExactServiceQuiescenceProbe(sup,contract()).observe().quiescent)

    def test_running_exact_process_blocks_retirement(self):
        with TemporaryDirectory() as td:
            c=contract(); process=ServiceProcessIdentity(123,'start')
            store=FileServiceStateStore(Path(td)/'state.json')
            state=ServiceSupervisorState.initial('svc',c.digest())
            store.write(ServiceSupervisorState(
                state.service_id,state.contract_digest,ServicePhase.RUNNING,1,process,'ready',None,None,None,None,None,state.updated_at,1234.5
            ))
            sup=make_service_supervisor(store,Adapter(process))
            observation=ExactServiceQuiescenceProbe(sup,c).observe()
            self.assertFalse(observation.quiescent)
            self.assertIn('still live',observation.summary)

    def test_unresolved_nonterminal_phase_blocks_even_when_no_process_is_visible(self):
        with TemporaryDirectory() as td:
            c=contract(); store=FileServiceStateStore(Path(td)/'state.json')
            state=ServiceSupervisorState.initial('svc',c.digest())
            store.write(ServiceSupervisorState(
                state.service_id,state.contract_digest,ServicePhase.START_CHILD,1,None,None,None,None,None,None,None,state.updated_at
            ))
            sup=make_service_supervisor(store,Adapter(None))
            observation=ExactServiceQuiescenceProbe(sup,c).observe()
            self.assertFalse(observation.quiescent)
            self.assertIn('not a quiescent terminal phase',observation.summary)

    def test_exited_state_without_process_is_quiescent(self):
        with TemporaryDirectory() as td:
            c=contract(); store=FileServiceStateStore(Path(td)/'state.json')
            state=ServiceSupervisorState.initial('svc',c.digest())
            store.write(ServiceSupervisorState(
                state.service_id,state.contract_digest,ServicePhase.EXITED,1,None,None,None,None,None,None,None,state.updated_at
            ))
            sup=make_service_supervisor(store,Adapter(None))
            self.assertTrue(ExactServiceQuiescenceProbe(sup,c).observe().quiescent)

if __name__=='__main__': unittest.main()
