from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.serving.api import (
    RuntimeCanaryContract,
    RuntimeCanaryProbe,
    ServiceHeartbeat,
)
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.capabilities.model.serving.composition import (
    qualify_and_publish_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import JsonHttpResponse
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PersistedQualifiedModelEndpointBinding,
    QualifiedModelClosurePublicationError,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
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
    ) -> JsonHttpResponse:
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
        canary_id="sem-planner-json",
        role="planner",
        suite_digest="8" * 64,
        request_body={
            "model": "planner-model",
            "messages": [{"role": "user", "content": "return status JSON"}],
            "chat_template_kwargs": {"enable_thinking": False},
        },
        contract=RuntimeCanaryContract(
            contract_id="sem-planner-exact-status",
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


def test_composition_runs_live_canary_binds_receipt_and_publishes_closure(tmp_path: Path) -> None:
    publication = _publication()
    deployment = publication.deployments[0]
    route = publication.routes[0]
    transport = _Transport('{"status":"ok"}')
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("qualification-closure")
    registry = ModelAdmissionRegistry()
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
        )
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
        role="planner", prompt_generation="sem-planner-generation-v1"
    )
    assert binding.deployment_id == deployment.deployment_id


def test_composition_rejects_semantic_canary_drift_without_exposing_closure(tmp_path: Path) -> None:
    publication = _publication()
    deployment = publication.deployments[0]
    transport = _Transport('{"status":"wrong"}')
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("qualification-closure-drift")
    registry = ModelAdmissionRegistry()
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
            )
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
    registry = ModelAdmissionRegistry()
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
            )
    finally:
        registry.close()
        runtime.close()
    assert transport.calls == []
