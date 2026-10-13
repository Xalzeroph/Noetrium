from __future__ import annotations

from model_admission_test_support import make_model_admission_registry

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import UnifiedSchedulingAuthority

from pathlib import Path
from dataclasses import replace
import asyncio

import pytest

from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    RuntimeCanaryContract,
    RuntimeCanaryProbe,
    ServiceHeartbeat,
)
from noetrium_platform.capabilities.model.serving.composition import (
    qualify_and_publish_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import JsonHttpResponse, ModelEndpointRoute
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PersistedQualifiedModelEndpointBinding,
    QualifiedModelClosurePublicationError,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from tests.test_qualified_closure_publication_v3 import _publication


class _Transport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, dict[str, object], float]] = []

    async def post_json(
        self,
        url: str,
        body: dict[str, object],
        *,
        timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> JsonHttpResponse:
        del headers
        self.calls.append((url, body, timeout_s))
        return JsonHttpResponse(200, {
            "choices": [{
                "message": {"content": self.content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        })


def _heartbeat(publication) -> ServiceHeartbeat:
    receipt = publication.runtime_qualification_receipts[0]
    return ServiceHeartbeat(
        receipt.deployment_id,
        receipt.stack_digest,
        receipt.process_pid,
        receipt.process_start_marker,
        receipt.argv_digest,
        True,
        receipt.heartbeat_qualification_digest,
        receipt.heartbeat_timestamp,
    )


def _probe() -> RuntimeCanaryProbe:
    return RuntimeCanaryProbe(
        canary_id="demo-planner-json",
        role="planner",
        suite_digest="8" * 64,
        request_body={
            "model": "planner-model",
            "messages": [{"role": "user", "content": "return status JSON"}],
            "chat_template_kwargs": {"enable_thinking": False},
        },
        contract=RuntimeCanaryContract(
            contract_id="demo-planner-exact-status",
            require_json_object=True,
            required_json_keys=("status",),
            allowed_finish_reasons=("stop",),
            expected_json_digest=canonical_digest({"status": "ok"}),
        ),
    )


def _load(path: Path):
    return load_qualified_model_deployment_closure(
        path,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )


@pytest.mark.parametrize("serial_workers", (1, 2))
def test_composition_runs_live_canary_binds_receipt_and_publishes_closure(tmp_path: Path, serial_workers: int) -> None:
    publication = _publication()
    deployment = publication.deployments[0]
    route = publication.routes[0]
    transport = _Transport('{"status":"ok"}')
    runtime = build_concurrency_runtime(budget=ConcurrencyBudget(
        max_serial_workers=serial_workers,
        max_blocking_io_workers=1,
        max_cpu_workers=1,
    ))
    group = runtime.open_task_group("qualification-closure")
    registry = make_model_admission_registry()
    path = tmp_path / "qualified.json"
    try:
        receipt = qualify_and_publish_model_deployment_closure(
            path,
            role_manifest=publication.role_manifest,
            deployments=publication.deployments,
            routes=publication.routes,
            heartbeats=(_heartbeat(publication),),
            canary_probes=(_probe(),),
            runtime_manifest_digest=publication.runtime_manifest_digest,
            max_heartbeat_age_seconds=60.0,
            task_group=group,
            admission_registry=registry,
            transports_by_deployment={deployment.deployment_id: transport},
         scheduling_authority=UnifiedSchedulingAuthority())
    finally:
        registry.close()
        runtime.close()

    assert len(receipt.runtime_canary_evidence_paths) == 1
    closure = _load(path)
    runtime_receipt = closure.runtime_qualifications.load(
        publication.runtime_manifest_digest, deployment.deployment_id
    )
    assert any(ref.startswith("canary:sha256:") for ref in runtime_receipt.evidence_refs)
    assert len(transport.calls) == 1
    binding = PersistedQualifiedModelEndpointBinding(closure).binding_for(
        role="planner", capability_id="generation", input_schema_id="model.generation.request.v1", output_schema_id="model.generation.response.v1", prompt_generation="demo-planner-generation-v1"
    )
    assert binding.deployment_id == deployment.deployment_id


def test_composition_rejects_semantic_canary_drift_without_exposing_closure(tmp_path: Path) -> None:
    publication = _publication()
    deployment = publication.deployments[0]
    transport = _Transport('{"status":"wrong"}')
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("qualification-closure-drift")
    registry = make_model_admission_registry()
    path = tmp_path / "qualified.json"
    try:
        with pytest.raises(QualifiedModelClosurePublicationError, match="did not pass"):
            qualify_and_publish_model_deployment_closure(
                path,
                role_manifest=publication.role_manifest,
                deployments=publication.deployments,
                routes=publication.routes,
                heartbeats=(_heartbeat(publication),),
                canary_probes=(_probe(),),
                runtime_manifest_digest=publication.runtime_manifest_digest,
                max_heartbeat_age_seconds=60.0,
                task_group=group,
                admission_registry=registry,
                transports_by_deployment={deployment.deployment_id: transport},
             scheduling_authority=UnifiedSchedulingAuthority())
    finally:
        registry.close()
        runtime.close()
    assert not path.exists()


def test_composition_rejects_missing_canary_role_before_network(tmp_path: Path) -> None:
    publication = _publication()
    deployment = publication.deployments[0]
    transport = _Transport('{"status":"ok"}')
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("qualification-closure-missing")
    registry = make_model_admission_registry()
    try:
        with pytest.raises(ValueError, match="probe coverage mismatch"):
            qualify_and_publish_model_deployment_closure(
                tmp_path / "qualified.json",
                role_manifest=publication.role_manifest,
                deployments=publication.deployments,
                routes=publication.routes,
                heartbeats=(_heartbeat(publication),),
                canary_probes=(),
                runtime_manifest_digest=publication.runtime_manifest_digest,
                max_heartbeat_age_seconds=60.0,
                task_group=group,
                admission_registry=registry,
                transports_by_deployment={deployment.deployment_id: transport},
             scheduling_authority=UnifiedSchedulingAuthority())
    finally:
        registry.close()
        runtime.close()
    assert transport.calls == []


def test_canaries_overlapping_across_independent_deployments(tmp_path: Path) -> None:
    """Both physical canaries must enter the model I/O loop before either returns."""
    publication = _publication()
    first = publication.deployments[0]
    second = replace(
        first,
        deployment_id="deployment-2",
        placement=DeploymentPlacement(("GPU-2",)),
    )
    first_route = publication.routes[0]
    second_route = ModelEndpointRoute(
        second.deployment_id,
        second.digest(),
        "http://127.0.0.1:30001",
        timeout_s=first_route.timeout_s,
    )

    class ConcurrentTransport(_Transport):
        def __init__(self) -> None:
            super().__init__('{"status":"ok"}')
            self.both_started = asyncio.Event()

        async def post_json(self, url, body, *, timeout_s, headers=()):
            self.calls.append((url, body, timeout_s))
            if len(self.calls) == 2:
                self.both_started.set()
            await asyncio.wait_for(self.both_started.wait(), timeout=3.0)
            return JsonHttpResponse(200, {
                "choices": [{
                    "message": {"content": self.content},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            })

    transport = ConcurrentTransport()
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("qualification-parallel-deployments")
    registry = make_model_admission_registry()
    try:
        receipt = qualify_and_publish_model_deployment_closure(
            tmp_path / "qualified.json",
            role_manifest=publication.role_manifest,
            deployments=(first, second),
            routes=(first_route, second_route),
            heartbeats=(
                _heartbeat(publication),
                replace(_heartbeat(publication), deployment_id=second.deployment_id),
            ),
            canary_probes=(_probe(),),
            runtime_manifest_digest=publication.runtime_manifest_digest,
            max_heartbeat_age_seconds=60.0,
            task_group=group,
            admission_registry=registry,
            transports_by_deployment={
                first.deployment_id: transport,
                second.deployment_id: transport,
            },
            scheduling_authority=UnifiedSchedulingAuthority(),
        )
    finally:
        registry.close()
        runtime.close()

    assert len(transport.calls) == 2
    assert len(receipt.runtime_canary_evidence_paths) == 2
    closure = _load(tmp_path / "qualified.json")
    assert len(closure.deployments) == 2
