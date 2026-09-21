from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    QualifiedDeploymentManifest,
    RuntimeCanaryEvidence,
    ServiceHeartbeat,
    build_runtime_qualification_receipt,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointRoute
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PersistedQualifiedModelEndpointBinding,
    load_qualified_model_deployment_closure,
    publish_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from tests.test_qualified_closure_publication_v3 import _publication


def test_persisted_binding_discovers_all_valid_exact_model_replicas(tmp_path: Path) -> None:
    base = _publication()
    first = base.deployments[0]
    second = QualifiedDeploymentManifest(
        "deployment-2",
        first.stack,
        first.certificate,
        DeploymentPlacement(("GPU-2",)),
        first.host_identity_digest,
    )
    route = ModelEndpointRoute(
        second.deployment_id,
        second.digest(),
        "http://127.0.0.1:30001",
        timeout_s=base.routes[0].timeout_s,
    )
    now = time.time()
    heartbeat = ServiceHeartbeat(
        second.deployment_id,
        second.stack.digest(),
        456,
        "start-456",
        "7" * 64,
        True,
        second.certificate.digest(),
        now - 0.1,
    )
    heartbeat_ref = (
        f"heartbeat:{heartbeat.deployment_id}:{heartbeat.pid}:"
        f"{heartbeat.process_start_marker}:{heartbeat.timestamp}"
    )
    receipt = build_runtime_qualification_receipt(
        second,
        heartbeat,
        required_roles=("planner",),
        evidence_refs=(heartbeat_ref,),
        max_heartbeat_age_seconds=60.0,
        now=now,
    )
    canary = RuntimeCanaryEvidence(
        deployment_id=second.deployment_id,
        deployment_generation=second.digest(),
        route_digest=canonical_digest(route),
        role="planner",
        canary_id="planner-json-replica",
        suite_digest="8" * 64,
        process_pid=receipt.process_pid,
        process_start_marker=receipt.process_start_marker,
        argv_digest=receipt.argv_digest,
        request_digest="9" * 64,
        probe_digest="0" * 64,
        response_digest="a" * 64,
        contract_digest="b" * 64,
        passed=True,
        observed_at=now,
    )
    receipt = replace(
        receipt,
        evidence_refs=(
            *receipt.evidence_refs,
            f"canary:sha256:{canary.evidence_digest}",
        ),
    )
    publication = replace(
        base,
        deployments=(base.deployments[0], second),
        routes=(base.routes[0], route),
        runtime_qualification_receipts=(
            base.runtime_qualification_receipts[0],
            receipt,
        ),
        runtime_canary_evidence=(
            base.runtime_canary_evidence[0],
            canary,
        ),
    )
    path = tmp_path / "qualified.json"
    publish_qualified_model_deployment_closure(
        path,
        publication,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )
    closure = load_qualified_model_deployment_closure(
        path,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )

    replicas = PersistedQualifiedModelEndpointBinding(closure).replica_set_for(
        role="planner",
        prompt_generation="prompt-v1",
    )

    assert tuple(row.deployment_id for row in replicas.bindings) == (
        "deployment-1",
        "deployment-2",
    )
    assert replicas.bindings[0].model == replicas.bindings[1].model
    assert replicas.bindings[0].model_stack_digest == replicas.bindings[1].model_stack_digest
    assert len(replicas.replica_set_digest) == 64
