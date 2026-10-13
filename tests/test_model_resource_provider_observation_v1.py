from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.deployment.api import (
    ModelAppliedServiceAbsent,
    ModelDeploymentGeneration,
    ModelDeploymentStatus,
    ModelDesiredDeployment,
    ModelDesiredState,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.runtime.resource_provider import (
    ModelServicePhysicalProvider,
    model_resource_deployment_id,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.substrate.api import observation_field, realization_ticket


class _Catalog:
    def __init__(self, spec: ModelDesiredDeployment) -> None:
        self.spec = spec

    def put_deployment(self, spec):
        self.spec = spec
        return spec

    def deployment(self, deployment_id):
        if deployment_id != self.spec.deployment_id:
            raise KeyError(deployment_id)
        return self.spec

    def deployments(self):
        return (self.spec,)


class _Runtime:
    def __init__(
        self,
        spec: ModelDesiredDeployment,
        *,
        recovery: str,
    ) -> None:
        self.spec = spec
        self.recovery = recovery
        self.recover_calls = 0
        self.applied_digest = None

    def generation(self, deployment_id):
        return ModelDeploymentGeneration(
            deployment_id,
            canonical_digest(self.spec),
            self.applied_digest,
        )

    def recover_applied(self, generation):
        self.recover_calls += 1
        if self.recovery == "absent":
            raise ModelAppliedServiceAbsent(generation.deployment_id)
        if self.recovery == "drift":
            raise RuntimeError("exact service contract drift")
        self.applied_digest = "c" * 64
        return ModelDeploymentGeneration(
            generation.deployment_id,
            generation.desired_deployment_digest,
            self.applied_digest,
        )

    def status(self, deployment_id):
        return ModelDeploymentStatus(
            deployment_id,
            self.spec.service_id,
            ModelDesiredState.RUNNING,
            (
                ModelRuntimeState.RUNNING
                if self.applied_digest is not None
                else ModelRuntimeState.STOPPED
            ),
            123 if self.applied_digest is not None else None,
            "ready" if self.applied_digest is not None else "not-applied",
        )


def _fixture(recovery: str):
    resource_key = "model:test"
    generation = 1
    deployment_id = model_resource_deployment_id(resource_key, generation)
    spec = ModelDesiredDeployment(
        deployment_id=deployment_id,
        scope=PLATFORM_SCOPE,
        service_id="model:" + deployment_id,
        model_id="Qwen3-8B",
        engine="vllm",
        container_digest="a" * 64,
        executable="/usr/local/bin/vllm",
        argv=("/usr/local/bin/vllm", "serve", "{model_path}"),
        cwd=Path("/tmp"),
        desired_state=ModelDesiredState.RUNNING,
    )
    runtime = _Runtime(spec, recovery=recovery)
    provider = ModelServicePhysicalProvider(
        catalog=_Catalog(spec),
        runtime=runtime,
    )
    ticket = realization_ticket(
        ticket_id="ticket",
        effect_id="effect",
        realization_key="realization",
        resource_key=resource_key,
        provider_kind=provider.provider_kind,
        generation=generation,
        spec_digest="b" * 64,
        holder_key="holder",
    )
    return runtime, provider, ticket


def test_model_provider_observe_projects_proved_exact_absence() -> None:
    runtime, provider, ticket = _fixture("absent")

    observed = provider.observe(ticket)

    assert runtime.recover_calls == 1
    assert observation_field(observed, "exists") is False
    assert observation_field(observed, "ready") is False
    assert observation_field(observed, "physical_identity") is None
    evidence = dict(observation_field(observed, "evidence") or {})
    assert evidence["runtime_state"] == ModelRuntimeState.MISSING.value
    assert evidence["applied_runtime_digest"] is None


def test_model_provider_observe_recovers_exact_live_applied_proof() -> None:
    runtime, provider, ticket = _fixture("live")

    observed = provider.observe(ticket)

    assert runtime.recover_calls == 1
    assert observation_field(observed, "exists") is True
    assert observation_field(observed, "ready") is True
    physical = observation_field(observed, "physical_identity")
    assert physical is not None
    evidence = dict(observation_field(observed, "evidence") or {})
    assert evidence["applied_runtime_digest"] == "c" * 64
    assert evidence["pid"] == 123


def test_model_provider_observe_does_not_collapse_recovery_drift_into_absence() -> None:
    _runtime, provider, ticket = _fixture("drift")

    with pytest.raises(RuntimeError, match="exact service contract drift"):
        provider.observe(ticket)
