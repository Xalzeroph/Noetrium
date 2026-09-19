from __future__ import annotations

import ast
from dataclasses import fields
import inspect
from pathlib import Path

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocationPort,
    EndpointAllocationRequest,
)
from noetrium_platform.infrastructure.resources.compute.api import ComputeRequirement
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import (
    ProcessCommandRunnerPort,
    ProcessSupervisorPort,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ExactServiceRuntimePort,
    ServiceLaunchContract,
    ServiceProcessIdentity,
    ServiceReadyObservation,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


_DIGEST = "a" * 64

def _service(service_id: str, generation: str, executable: str) -> ServiceLaunchContract:
    return ServiceLaunchContract(
        service_id=service_id,
        generation=generation,
        executable=executable,
        argv=(executable, "--serve"),
        cwd="/work",
        environment_digest=_DIGEST,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
        readiness_timeout_s=30.0,
        stop_timeout_s=10.0,
        heartbeat_interval_s=2.0,
    )


class _ExactRuntimeDouble(ExactServiceRuntimePort):
    def __init__(self) -> None:
        self.started: list[str] = []

    def reconcile_exact(self, contract: ServiceLaunchContract) -> ServiceReconcileObservation:
        return ServiceReconcileObservation(False, None, (f"reconcile:{contract.generation}",))

    def start_exact(self, contract: ServiceLaunchContract) -> ServiceStartOutcome:
        self.started.append(contract.digest())
        process = ServiceProcessIdentity(len(self.started) + 100, f"start:{contract.generation}")
        return ServiceStartOutcome(contract.digest(), process, f"ready:{contract.generation}", 1000.0, ())

    def verify_ready_exact(self, contract: ServiceLaunchContract) -> ServiceReadyObservation:
        process = ServiceProcessIdentity(101, f"start:{contract.generation}")
        return ServiceReadyObservation(contract.digest(), process, f"ready:{contract.generation}", 1000.0, ())

    def stop_exact(self, contract: ServiceLaunchContract) -> ServiceStopOutcome:
        return ServiceStopOutcome(contract.digest(), True, (f"stopped:{contract.generation}",))


def test_training_and_streaming_workers_share_one_transport_neutral_service_lifecycle() -> None:
    runtime: ExactServiceRuntimePort = _ExactRuntimeDouble()
    training = _service("trainer", "train-g1", "/opt/research/train-worker")
    streaming = _service("stream", "stream-g1", "/opt/research/stream-provider")

    train_started = runtime.start_exact(training)
    stream_started = runtime.start_exact(streaming)

    assert train_started.contract_digest == training.digest()
    assert stream_started.contract_digest == streaming.digest()
    assert runtime.verify_ready_exact(training).ready_at == 1000.0
    assert runtime.stop_exact(streaming).stopped
    assert training.digest() != streaming.digest()


def test_training_and_streaming_resource_shapes_use_public_requirements_and_endpoint_binding() -> None:
    training = ComputeRequirement(
        cpu_cores=16,
        memory_bytes=64 * 1024**3,
        gpu_count=2,
        minimum_gpu_memory_bytes=24 * 1024**3,
        required_labels=(("workload", "training"),),
    )
    streaming = ComputeRequirement(
        cpu_cores=8,
        memory_bytes=32 * 1024**3,
        gpu_count=1,
        minimum_gpu_memory_bytes=16 * 1024**3,
        required_labels=(("workload", "streaming"),),
    )
    endpoint = EndpointAllocationRequest(
        "stream-endpoint-g1", PLATFORM_SCOPE, "streaming provider", "0.0.0.0", (41000, 41001)
    )

    assert training.gpu_count == 2
    assert streaming.minimum_gpu_memory_bytes < training.minimum_gpu_memory_bytes
    assert tuple(row.port for row in endpoint.candidates()) == (41000, 41001)


def test_generation_rebind_and_bounded_process_controls_are_explicit_public_semantics() -> None:
    generation_one = _service("trainer", "train-g1", "/opt/research/train-worker")
    generation_two = _service("trainer", "train-g2", "/opt/research/train-worker")
    assert generation_one.digest() != generation_two.digest()

    replace = inspect.signature(EndpointAllocationPort.replace_bound)
    terminate = inspect.signature(ProcessSupervisorPort.terminate)
    execute = inspect.signature(ProcessCommandRunnerPort.execute)

    assert "expected_previous_binding_proof_digest" in replace.parameters
    assert "deadline" in terminate.parameters
    assert "timeout_seconds" in execute.parameters
    assert "output_limit_bytes" in execute.parameters


def test_service_contract_keeps_transport_placement_out_of_lifecycle_identity_shape() -> None:
    names = {field.name for field in fields(ServiceLaunchContract)}
    assert not ({"server_id", "host", "ssh_profile", "connection"} & names)
    assert {"service_id", "generation", "artifact_digest", "runtime_identity_digest"} <= names


def test_pge_reference_consumer_uses_public_api_modules_only() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imports = tuple(
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("noetrium_platform.")
    )
    assert imports
    assert all(".api" in module for module in imports)
    assert all(".providers" not in module and ".composition" not in module for module in imports)
