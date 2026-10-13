"""Refresh must borrow canonical adaptive model owners, not allocate a duplicate fleet."""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from noetrium_platform.composition import model_runtime_refresh as refresh
from noetrium_platform.composition import model_runtime_bootstrap as bootstrap_module
from noetrium_platform.composition.model_runtime_bootstrap import RequiredModelRuntime
from noetrium_platform.infrastructure.resources.compute.api import ComputePlacementUnavailable, ComputeRequirement


class AdaptiveIdentityTests(TestCase):
    def test_refresh_request_uses_same_adaptive_replica_identity_as_bootstrap(self):
        from noetrium_platform.composition.model_runtime_bootstrap import _model_replica_request
        with TemporaryDirectory() as td:
            root = Path(td)
            class Stack:
                identity = SimpleNamespace(model_id='Qwen3-8B', engine='vllm', context_length=32768)
                tensor_parallel = 1
                pipeline_parallel = 1
                engine_args = ()
                def digest(self): return 'a'*64
            stack = Stack()
            compute = ComputeRequirement(cpu_cores=4, memory_bytes=8*1024**3, gpu_count=1, required_gpu_free_memory_bytes=1*1024**3)
            source = SimpleNamespace(deployment_id='old-model', stack=stack, certificate=SimpleNamespace(target_host_identity_digest='host',digest=lambda:'c'*64))
            closure = SimpleNamespace(deployments=(source,),role_manifest=SimpleNamespace(assignments=()),runtime_canary_evidence=(),runtime_manifest_digest='b'*64)
            authority_root = root / 'authority'
            path = authority_root / 'models' / 'Qwen3-8B' / 'qualified-model-closure.json'
            path.parent.mkdir(parents=True)
            path.write_text('{}')
            captured = []
            bootstrap_calls = []
            class Pool:
                def borrow_existing(self, request, *, expected_replica_count):
                    self_last_seen = request
                    assert expected_replica_count == 1
                    return None
                def ensure(self, request):
                    captured.append(request)
                    raise ComputePlacementUnavailable(compute)
                def reclaim_one_stale_warm_realization(self):return None
                def reclaim_dominated_warm_realizations(self):return ()
            class Inventory:
                def host(self, host):return object()
            from contextlib import ExitStack
            with ExitStack() as guards:
                for target, value in (
                    ('_load_strict',lambda path:closure),
                    ('_uses_current_model_qualification_protocol',lambda closure:True),
                    ('_closure_covers_required_model_rows',lambda closure,**kwargs:True),
                    ('_desired_stack_materializations',lambda topologies,**kwargs:{k:SimpleNamespace(stack=stack,compute=compute) for k in topologies}),
                    ('qualification_source_stack_digest',lambda stack:stack.digest()),
                    ('qualified_model_closure_path',lambda root,model_id:path),
                    ('ModelReplicaPoolRequest',lambda **kwargs:SimpleNamespace(**kwargs)),
                    ('bootstrap_required_qualified_model_runtime',lambda **kwargs:bootstrap_calls.append(kwargs) or 'new-cert'),
                ):
                    guards.enter_context(patch.object(refresh,target,value))
                guards.enter_context(patch.object(bootstrap_module, 'ModelReplicaPoolRequest', lambda **kwargs:SimpleNamespace(**kwargs)))
                result=refresh._refresh_required_qualified_model_runtimes_unfenced(
                    authority_root=authority_root,
                    required_models=(RequiredModelRuntime(model_id='Qwen3-8B',role='agent'),),
                    assets=object(),resource_authority=object(),model_resources=object(),
                    state_root=root/'state',runtime_workdir=root/'runtime',
                    model_replica_pool=Pool(),deployment_runtime=object(),compute_inventory=Inventory(),
                    gpu_runtime_observer=None,host_runtime_observer=None,execution_pool=object(),
                )
            self.assertEqual(result,('new-cert',))
            self.assertEqual(len(captured),1)
            self.assertIsNone(captured[0].replica_count)
            with patch.object(bootstrap_module, 'ModelReplicaPoolRequest', lambda **kwargs:SimpleNamespace(**kwargs)):
                bootstrap = _model_replica_request(model_id='Qwen3-8B',roles=('agent',),stack=stack,compute=compute,runtime_workdir=root/'runtime')
            self.assertEqual(captured[0].model_stack,bootstrap.model_stack)
            self.assertEqual(captured[0].compute,bootstrap.compute)
            self.assertEqual(captured[0].cwd,bootstrap.cwd)
            self.assertEqual(captured[0].scope,bootstrap.scope)
            self.assertEqual(len(bootstrap_calls),1)
