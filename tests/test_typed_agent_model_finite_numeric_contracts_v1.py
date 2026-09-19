from __future__ import annotations

from math import inf, nan
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.deployment.api import (
    ModelControllerPhase,
    ModelControllerState,
    ModelDeploymentSpec,
    ModelDesiredState,
)
from noetrium_platform.capabilities.model.qualification.api import DeploymentQualificationRequest
from noetrium_platform.capabilities.model.request.prompt.runtime.spec import PromptSection, PromptSpec
from noetrium_platform.capabilities.model.serving.api import PerformanceSample, QualificationPolicy, ResourceEnvelope
from noetrium_platform.capabilities.model.serving.endpoint import ModelEndpointRoute
from noetrium_platform.capabilities.participant.agent.api import AgentGoal
from noetrium_platform.capabilities.participant.agent.runtime.vision import VisionInterpretation
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


NON_FINITE = (nan, inf, -inf)


def _deployment(**changes: object) -> ModelDeploymentSpec:
    values: dict[str, object] = {
        "deployment_id": "dep",
        "scope": PLATFORM_SCOPE,
        "service_id": "svc",
        "model_id": "model",
        "engine": "engine",
        "executable": "python",
        "argv": ("python", "-m", "server"),
        "cwd": Path("C:/runtime"),
        "readiness_timeout_s": 12.0,
        "stop_timeout_s": 5.0,
        "heartbeat_interval_s": 2.0,
        "desired_state": ModelDesiredState.RUNNING,
    }
    values.update(changes)
    return ModelDeploymentSpec(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", NON_FINITE)
def test_agent_goal_rejects_non_finite_time_budget(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        AgentGoal("goal", "objective", max_seconds=value)


@pytest.mark.parametrize("value", NON_FINITE)
def test_vision_confidence_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError):
        VisionInterpretation("frame", (), "observed", value)


@pytest.mark.parametrize("field", ("readiness_timeout_s", "stop_timeout_s", "heartbeat_interval_s"))
@pytest.mark.parametrize("value", NON_FINITE)
def test_model_deployment_rejects_non_finite_time_controls(field: str, value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _deployment(**{field: value})


@pytest.mark.parametrize("value", NON_FINITE)
def test_model_controller_and_qualification_reject_non_finite_controls(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        ModelControllerState(
            "controller",
            ModelControllerPhase.RUNNING,
            None,
            "start",
            "heartbeat",
            value,
            0,
        )
    with pytest.raises(ValueError, match="finite"):
        DeploymentQualificationRequest(
            "model",
            Path("C:/models/model"),
            Path("C:/python/python.exe"),
            probe_timeout_seconds=value,
        )


@pytest.mark.parametrize("value", NON_FINITE)
def test_model_endpoint_route_rejects_non_finite_timeout(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        ModelEndpointRoute("dep", "a" * 64, "http://127.0.0.1:8000", timeout_s=value)


@pytest.mark.parametrize("value", NON_FINITE)
def test_prompt_sampling_authority_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        PromptSpec(
            "planner.v1",
            "planner",
            "1",
            "model",
            "schema",
            (PromptSection("role", "plan", 1),),
            value,
            0.95,
            128,
        )
    with pytest.raises(ValueError, match="finite"):
        PromptSpec(
            "planner.v1",
            "planner",
            "1",
            "model",
            "schema",
            (PromptSection("role", "plan", 1),),
            0.1,
            value,
            128,
        )


@pytest.mark.parametrize("field", ("ttft_p50", "ttft_p99", "tpot_p50", "tpot_p99", "output_tokens_per_second", "error_rate"))
@pytest.mark.parametrize("value", NON_FINITE)
def test_performance_sample_rejects_non_finite_measurements(field: str, value: float) -> None:
    values = {
        "concurrency": 2,
        "ttft_p50": 0.1,
        "ttft_p99": 0.2,
        "tpot_p50": 0.01,
        "tpot_p99": 0.02,
        "output_tokens_per_second": 50.0,
        "error_rate": 0.0,
    }
    values[field] = value
    with pytest.raises(ValueError, match="finite"):
        PerformanceSample(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ("minimum_role_pass_rate", "max_error_rate"))
@pytest.mark.parametrize("value", NON_FINITE)
def test_qualification_policy_rejects_non_finite_thresholds(field: str, value: float) -> None:
    values = {"minimum_role_pass_rate": 0.98, "max_error_rate": 0.001}
    values[field] = value
    with pytest.raises(ValueError, match="finite"):
        QualificationPolicy(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ("ttft_p99_seconds", "tpot_p99_seconds", "minimum_output_tokens_per_second"))
@pytest.mark.parametrize("value", NON_FINITE)
def test_resource_envelope_rejects_non_finite_performance_authority(field: str, value: float) -> None:
    values = {
        "peak_gpu_memory_bytes_per_device": 1,
        "peak_host_memory_bytes": 1,
        "max_qualified_concurrency": 1,
        "ttft_p99_seconds": 0.2,
        "tpot_p99_seconds": 0.02,
        "minimum_output_tokens_per_second": 50.0,
    }
    values[field] = value
    with pytest.raises(ValueError, match="finite"):
        ResourceEnvelope(**values)  # type: ignore[arg-type]


def test_qualification_rates_remain_bounded_probabilities() -> None:
    with pytest.raises(ValueError, match="error_rate"):
        PerformanceSample(1, 0.1, 0.2, 0.01, 0.02, 10.0, 1.01)
    with pytest.raises(ValueError, match="within"):
        QualificationPolicy(minimum_role_pass_rate=1.01)


from noetrium_platform.capabilities.model.request.prompt.api.request import PromptBodyContext
from noetrium_platform.capabilities.model.request.prompt.api.trace import (
    PromptTracePoint,
    PromptTraceStage,
    PromptTraceSummary,
)
from noetrium_platform.capabilities.model.request.prompt.runtime.outcome import (
    PromptOutcomeLink,
    PromptOutcomeSummary,
)
from noetrium_platform.capabilities.model.request.prompt.runtime.promotion_contracts import (
    PromptPromotionEvidence,
    PromptPromotionRecord,
)
from noetrium_platform.capabilities.model.request.prompt.runtime.request_contract import PromptRequestContract
from noetrium_platform.capabilities.model.request.prompt.runtime.runtime_contracts import ActivePromptBundle
from noetrium_platform.capabilities.model.serving.api.heartbeat import ServiceHeartbeat
from noetrium_platform.capabilities.model.serving.api.inventory import (
    CPUInventory,
    CPUNode,
    GPUFabricLink,
    GPUInventory,
)
from noetrium_platform.capabilities.model.serving.api.inventory import (
    HostInventory,
    HostLimits,
    MemoryInventory,
    MountInventory,
    RuntimeInventory,
)
from noetrium_platform.capabilities.model.serving.api.recovery_state import (
    DurableRecoveryAttempt,
    DurableRecoveryPhase,
)
from noetrium_platform.capabilities.model.serving.api.state import ModelPhase, ModelRunState
from noetrium_platform.capabilities.model.serving.endpoint.api.qualification import QualifiedModelEndpointBinding
from noetrium_platform.capabilities.model.qualification.api import (
    CudaFacts,
    DeploymentCapabilityFacts,
    GpuCapabilityFacts,
    HostExecutionFacts,
    ModelArtifactFacts,
    OperatingSystemFacts,
    PythonRuntimeFacts,
    StorageCapabilityFacts,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _model_identity() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        "planner", "repo/model", "rev", "sglang", "1", "bfloat16", None, 8192
    )


def _host_inventory(*, captured_at: float) -> HostInventory:
    return HostInventory(
        "host",
        captured_at,
        CPUInventory("x86_64", 1, (0,), None, (CPUNode(0, (0,), 1),)),
        MemoryInventory(1, 1, None, None),
        (),
        (),
        (MountInventory("/", "fs", "dev", 1, 1, None, False),),
        RuntimeInventory("kernel", "python", None, None, None, None, None, None, None),
        HostLimits(1, 1, None),
        (),
    )


def _capability_facts(*, captured_at: float) -> DeploymentCapabilityFacts:
    return DeploymentCapabilityFacts(
        captured_at,
        OperatingSystemFacts("Windows", "Windows", "11", "kernel", "x86_64"),
        CudaFacts(None, None, None),
        (),
        PythonRuntimeFacts("python", "3.12", None, True, True, None, None, None),
        ModelArtifactFacts("model", "C:/model", None, (), None, None, True),
        (),
        host=HostExecutionFacts("host", "x86_64", 1),
        storage=StorageCapabilityFacts("C:/model"),
    )


@pytest.mark.parametrize("value", NON_FINITE)
def test_prompt_runtime_authority_rejects_non_finite_sampling(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        PromptBodyContext("p", "a" * 64, "planner", "model", "schema", "text", value, 0.9, 32)
    with pytest.raises(ValueError, match="finite"):
        ActivePromptBundle("p", "planner", "1", "a" * 64, "text", "schema", "model", value, 0.9, 32)
    with pytest.raises(ValueError, match="finite"):
        PromptRequestContract("r", "g", "p", "a" * 64, "planner", ("model",), "b" * 64, value, 0.9, 32)


@pytest.mark.parametrize("value", NON_FINITE)
def test_prompt_trace_outcome_and_promotion_reject_non_finite_authority(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        PromptTracePoint(PromptTraceStage.REQUEST_CREATED, value, ())
    with pytest.raises(ValueError, match="finite"):
        PromptTraceSummary("r", "planner", "model", "d", (), value, None, None, None, None, None, None, None, None)
    with pytest.raises(ValueError, match="finite"):
        PromptOutcomeLink("r", "p", "t", "cycle", None, True, True, value, 0)
    with pytest.raises(ValueError, match="finite"):
        PromptOutcomeSummary("p", 1, 1.0, 1.0, value)
    with pytest.raises(ValueError, match="finite"):
        PromptPromotionEvidence("g", "a" * 64, "suite", (), (), "b" * 64, value)
    with pytest.raises(ValueError, match="finite"):
        PromptPromotionRecord("g", "a" * 64, "b" * 64, None, value)


@pytest.mark.parametrize("value", NON_FINITE)
def test_model_temporal_authority_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        ServiceHeartbeat("dep", "stack", 1, "start", "argv", True, None, value)
    with pytest.raises(ValueError, match="finite"):
        _host_inventory(captured_at=value)
    with pytest.raises(ValueError, match="finite"):
        _capability_facts(captured_at=value)


@pytest.mark.parametrize("value", NON_FINITE)
def test_model_inventory_measurements_reject_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        CPUInventory("x86_64", 1, (0,), value, (CPUNode(0, (0,), 1),))
    with pytest.raises(ValueError, match="finite"):
        GPUInventory("gpu", "GPU", 1, 1, "bus", 0, "9.0", value)
    with pytest.raises(ValueError, match="finite"):
        GPUFabricLink("a", "b", "NVLink", value)
    with pytest.raises(ValueError, match="finite"):
        GpuCapabilityFacts("0", "gpu", "GPU", 1, 1, "9.0", power_limit_watts=value)


@pytest.mark.parametrize("value", NON_FINITE)
def test_model_recovery_and_run_state_reject_non_finite_timestamps(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        DurableRecoveryAttempt(
            "attempt", "run", "a" * 64, DurableRecoveryPhase.PLANNED,
            (), None, None, None, (), value,
        )
    with pytest.raises(ValueError, match="finite"):
        ModelRunState(
            "run", _model_identity(), "a" * 64, ModelPhase.NEW,
            value, 1.0,
        )


@pytest.mark.parametrize("value", NON_FINITE)
def test_qualified_binding_rejects_non_finite_timeout(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        QualifiedModelEndpointBinding(
            role="planner",
            deployment_id="dep",
            deployment_generation="a" * 64,
            base_url="http://127.0.0.1:8000",
            model=_model_identity(),
            model_stack_digest="b" * 64,
            qualification_certificate_digest="c" * 64,
            runtime_qualification_digest="d" * 64,
            host_identity_digest="e" * 64,
            prompt_generation="prompt-gen",
            max_admitted_concurrency=1,
            runtime_canary_evidence_digests=("f" * 64,),
            timeout_s=value,
        )
