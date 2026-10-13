"""Noetrium model serving telemetry and physical transport ownership regressions."""
from __future__ import annotations

import asyncio
import unittest

from noetrium_platform.capabilities.model.serving.endpoint.providers.vllm_pressure import (
    VllmRuntimePressureObserver,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    ModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_adaptive_model_endpoint_pool,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import UnifiedSchedulingAuthority
from model_admission_test_support import make_model_admission_registry


class _MetricsTransport:
    def __init__(self, text: str):
        self.text = text

    async def get_text(self, url: str, *, timeout_s: float, headers=()) -> str:
        assert url.endswith('/metrics') and timeout_s > 0
        return self.text


class ModelServingPressureTransportTests(unittest.TestCase):
    def _pressure(self, body: str):
        observer = VllmRuntimePressureObserver(_MetricsTransport(body), clock=lambda: 17.0)
        route = ModelEndpointRoute('test-deployment', 'a' * 64, 'http://127.0.0.1:18888')
        return asyncio.run(observer.snapshot(route))

    def test_vllm_v1_metrics_preferred_without_double_counting_aliases(self):
        snapshot = self._pressure('''
 vllm:kv_cache_usage_perc{model_name="qwen"} 0.81
 vllm:gpu_cache_usage_perc{model_name="qwen"} 0.13
 vllm:prefix_cache_queries_total{model_name="qwen"} 100
 vllm:prefix_cache_hits_total{model_name="qwen"} 65
 vllm:gpu_prefix_cache_queries_total{model_name="qwen"} 500
 vllm:gpu_prefix_cache_hits_total{model_name="qwen"} 50
 vllm:num_requests_running{model_name="qwen"} 3
 vllm:num_requests_waiting{model_name="qwen"} 2
 vllm:num_preemptions_total{model_name="qwen"} 1
''')
        self.assertEqual(snapshot.gpu_kv_cache_usage, 0.81)
        self.assertEqual(snapshot.prefix_cache_hit_rate, 0.65)
        self.assertEqual(snapshot.requests_running, 3)
        self.assertEqual(snapshot.requests_waiting, 2)
        self.assertEqual(snapshot.preemptions_total, 1)

    def test_http_loop_lag_probe_detects_blocking_callback_without_detached_tasks(self):
        import time
        from noetrium_platform.capabilities.model.serving.endpoint.providers.http_pool import _HttpEventLoopLagProbe

        async def simulated_http_wait():
            probe = _HttpEventLoopLagProbe()
            await asyncio.sleep(0.065)
            time.sleep(0.15)  # simulate unexpected synchronous authority I/O
            await asyncio.sleep(0.015)
            return probe.stop()

        peak, accumulated = asyncio.run(simulated_http_wait())
        self.assertGreater(peak, 100_000_000)
        self.assertGreaterEqual(accumulated, peak)

    def test_legacy_metrics_remain_supported(self):
        snapshot = self._pressure('''
 vllm:gpu_cache_usage_perc{model_name="qwen"} 0.41
 vllm:gpu_prefix_cache_queries_total{model_name="qwen"} 20
 vllm:gpu_prefix_cache_hits_total{model_name="qwen"} 5
''')
        self.assertEqual(snapshot.gpu_kv_cache_usage, 0.41)
        self.assertEqual(snapshot.prefix_cache_hit_rate, 0.25)

    def test_raw_lake_observer_emits_stage_breakdown_with_exact_request_identity(self):
        from noetrium_platform.composition.model_raw_observation import RawLakeModelEndpointObserver
        from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
        from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointRequest, JsonHttpResponse
        from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
        from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity

        class Gateway:
            def __init__(self):
                self.records = []
            def register_producer(self, *args):
                pass
            def capture(self, record):
                self.records.append(record)

        gateway = Gateway()
        observer = RawLakeModelEndpointObserver(gateway)
        model = ImmutableModelIdentity('qwen', 'Qwen3-8B', 'rev', 'vllm', '1', 'bfloat16', None, 8192)
        envelope = ModelRequestEnvelope(
            schema_version='model-request.v1', request_id='timing-raw-1',
            context=ExecutionContext('timing-run', 'trace', 'span'),
            role='reasoner', model=model,
            prompt_generation_id='gen', prompt_id='p', prompt_digest='d' * 64,
            request_body=ArtifactBlobRef('f' * 64, 2, 'application/json'),
        )
        request = ModelEndpointRequest(
            request=envelope, deployment_id='model-deployment',
            deployment_generation='a' * 64,
            body={'model': 'Qwen3-8B', 'messages': [{'role': 'user', 'content': 'hello'}]},
        )
        observer.on_exchange(request, JsonHttpResponse(
            200,
            {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]},
            raw_body=b'{}', request_body=b'{}',
            stage_timings_ns=(('authority_release', 12345), ('http_headers_wait', 67890)),
        ), 100, 80000)
        self.assertEqual(len(gateway.records), 2)
        for record in gateway.records:
            self.assertEqual(dict(record.dimensions['stage_timings_ns']), {
                'authority_release': 12345, 'http_headers_wait': 67890,
            })
            self.assertEqual(record.stream_id, 'timing-raw-1')
            self.assertEqual(record.dimensions['duration_ns'], 79900)
        from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointError
        observer.on_failure(
            request,
            ModelEndpointError('model admission failed', failure_kind='timeout',
                               stage_timings_ns=(('authority_admission', 3456789),)),
            100, 1000,
        )
        self.assertEqual(len(gateway.records), 4)
        for record in gateway.records[2:]:
            self.assertEqual(dict(record.dimensions['stage_timings_ns']), {
                'authority_admission': 3456789,
            })
            self.assertEqual(record.stream_id, 'timing-raw-1')

    def test_cancelled_before_entry_retirement_is_fenced_and_affine(self):
        from noetrium_platform.capabilities.model.serving.endpoint.providers import NativeModelProviderEndpoint
        from noetrium_platform.capabilities.model.serving.endpoint.providers.native import _PhysicalRetirementGate
        from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled

        class Lease:
            def __init__(self):
                self.releases = 0
            def release(self):
                self.releases += 1

        class CancelledHandle:
            def done(self):
                return True
            def add_done_callback(self, callback):
                callback(self)
            def result(self, timeout=None):
                raise TaskCancelled("HTTP task physically cancelled before entry")

        lease = Lease()
        with self.assertRaises(TaskCancelled):
            NativeModelProviderEndpoint._await_and_retire(
                CancelledHandle(), lease, gate=_PhysicalRetirementGate(),
                timeout_seconds=None,
            )
        self.assertEqual(lease.releases, 1)

    def test_endpoint_stage_timings_capture_slow_authority_release(self):
        import time
        from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
        from noetrium_platform.capabilities.model.serving.endpoint.api import (
            JsonHttpResponse, ModelEndpointRequest,
        )
        from noetrium_platform.capabilities.model.serving.endpoint.providers import NativeModelProviderEndpoint
        from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
        from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
        from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind, ExecutionSpec, TaskFailureScope

        class Lease:
            def release(self):
                time.sleep(0.25)

        class Admission:
            capacity = 1
            def acquire(self, *args, **kwargs):
                time.sleep(0.015)
                return Lease()

        class Transport:
            async def post_json(self, url, body, *, timeout_s, headers=()):
                await asyncio.sleep(0.015)
                return JsonHttpResponse(200, {
                    "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                })

        class Observer:
            observer_id = "unit-test-model-timing"
            response = None
            def on_exchange(self, request, response, started, completed):
                self.response = response

        runtime = build_concurrency_runtime()
        group = runtime.open_task_group('model-profile-unittest')
        obs = Observer()
        async def event_loop_heartbeat(context):
            await asyncio.sleep(0.055)
            return time.perf_counter()
        started = time.perf_counter()
        heartbeat = group.submit(
            ExecutionSpec(
                task_id='event-loop-not-blocked-by-authority-release',
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            event_loop_heartbeat,
        )
        try:
            model = ImmutableModelIdentity(
                "planner", "Qwen3-8B", "revision", "vllm", "1",
                "bfloat16", None, 8192,
            )
            envelope = ModelRequestEnvelope(
                schema_version="model-request.v1", request_id="timed-request",
                context=ExecutionContext("run", "trace", "span"),
                role="planner", model=model,
                prompt_generation_id="prompt-gen", prompt_id="planner.prompt",
                prompt_digest="d" * 64,
                request_body=ArtifactBlobRef("f" * 64, 2, "application/json"),
            )
            route = ModelEndpointRoute("timed-model", "a" * 64, "http://127.0.0.1:18888")
            endpoint = NativeModelProviderEndpoint(
                route=route, transport=Transport(), task_group=group,
                admission=Admission(), observers=(obs,), owns_transport=False,
            )
            request = ModelEndpointRequest(
                request=envelope, deployment_id=route.deployment_id,
                deployment_generation=route.deployment_generation,
                body={"model": "Qwen3-8B", "messages": [{"role": "user", "content": "hello"}]},
            )
            result = endpoint.complete(request)
            self.assertEqual(result.text, "done")
            timings = dict(obs.response.stage_timings_ns)
            self.assertGreaterEqual(timings["authority_admission"], 15_000_000)
            self.assertGreaterEqual(timings["http_transport"], 15_000_000)
            self.assertGreaterEqual(timings["authority_release"], 250_000_000)
            self.assertLess(
                heartbeat.result(timeout=1) - started, 0.19,
                "Resource Authority release must not block the ASYNC_IO loop",
            )
            tasks = runtime.topology_snapshot().groups[0].tasks
            self.assertNotIn(ExecutionLaneKind.SERIAL, {t.lane_kind for t in tasks})
            self.assertGreater(timings["async_io_dispatch_wait"], 0)
            self.assertGreaterEqual(timings["submit_and_completion_wait"], timings["http_transport"])
            self.assertEqual(obs.response.stage_timings_ns, tuple(sorted(timings.items())))
        finally:
            runtime.close()

    def test_default_replica_pool_owns_one_shared_http_transport(self):
        registry = make_model_admission_registry()
        runtime = build_concurrency_runtime()
        group = runtime.open_task_group('model-transport-lifecycle-unittest')
        replicas = ModelEndpointReplicaSet(tuple(
            OperationalModelEndpointReplica(
                ModelEndpointRoute(f'unit-model-{i}', f'{i+1:064x}', 'http://127.0.0.1:18888'),
                2,
            ) for i in range(2)
        ))
        pool = None
        try:
            pool = build_adaptive_model_endpoint_pool(
                replicas,
                task_group=group,
                admission_registry=registry,
                scheduling_authority=UnifiedSchedulingAuthority(),
            )
            endpoints = [runtime.endpoint for runtime in pool._runtimes.values()]
            self.assertEqual(len(endpoints), 2)
            self.assertIs(endpoints[0].transport, endpoints[1].transport)
            self.assertIsNotNone(pool._owned_transport_close)
            self.assertFalse(endpoints[0]._owns_transport)
            pool.close()
            self.assertTrue(endpoints[0].transport._closed)
        finally:
            if pool is not None and not pool._closed:
                pool.close()
            registry.close()
            registry._test_tempdir.cleanup()
            runtime.close()


if __name__ == '__main__':
    unittest.main()
