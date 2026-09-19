from __future__ import annotations

import unittest

from noetrium_platform.capabilities.participant.capability.api import CapabilityDescriptor, CapabilityRequest, CapabilityResult
from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal, ComponentIdentity, EffectClass, ExecutionContext, OperationExecutor
from noetrium_platform.research.execution.workflow.implementations.agent_turn.capability_operations import CapabilityOperationAdapter
from noetrium_platform.research.execution.workflow.implementations.agent_turn.capability_routing import CapabilitySessionBinding, StudyCapabilityRouter
from noetrium_platform.research.execution.capability.runtime import (
    CapabilityInvocationPipelineFactory,
    ScopedRegistrationRuntime,
)
from noetrium_platform.research.execution.workflow.runtime import KernelOperationDispatcher


class Session:
    capabilities=(CapabilityDescriptor('tool.echo','1','echo.request.v1','echo.result.v1',EffectClass.PURE),)
    def invoke(self, request): return CapabilityResult(request.capability_id,request.payload)
    def checkpoint(self): return b''
    def restore(self,payload): pass
    def close(self): pass


class Provider:
    identity=None


class CapabilityOperationBoundaryV162Tests(unittest.TestCase):
    def test_router_uses_narrow_operation_adapter_without_owning_dispatcher(self):
        dispatcher=KernelOperationDispatcher(OperationExecutor())
        adapter=CapabilityOperationAdapter(dispatcher)
        component=ComponentIdentity('capability_provider.echo','echo','1','1','g')
        binding=CapabilitySessionBinding(component, Session(), "provider")
        router=StudyCapabilityRouter(
            adapter,
            (binding,),
            pipeline=CapabilityInvocationPipelineFactory(InMemoryMachineJournal()).create(),
            scope=ScopedRegistrationRuntime("test-capability-router"),
        )
        context=ExecutionContext(run_id='r',trace_id='t',span_id='s',platform_generation='p',decision_cycle_id='dc')
        result=router.invoke(CapabilityRequest('tool.echo',{'x':1},context))
        self.assertEqual(result.payload,{'x':1})
        operations=router.drain_operations()
        self.assertEqual(len(operations),1)
        self.assertEqual(operations[0].operation_id,'dc:capability.invoke:tool.echo')
        self.assertFalse(hasattr(router,'_dispatcher'))

if __name__=='__main__': unittest.main()
