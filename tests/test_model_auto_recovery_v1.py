from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentGeneration,
    ModelDeploymentSpec,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.runtime import (
    DurableModelAutoRecoveryAuthority,
    ModelAutoRecoveryPolicy,
    ModelFleetRuntime,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout
from noetrium_platform.infrastructure.resources.directory.runtime import (
    build_local_directory_authorities,
)


def _layout(root: Path) -> DirectoryLayout:
    return DirectoryLayout(
        releases=root / "releases",
        runtime=root / "runtime",
        state=root / "state",
        logs=root / "logs",
        model_artifacts=root / "models",
        python_environments=root / "envs",
        cache=root / "cache",
        temp=root / "temp",
        locks=root / "locks",
        workspaces=root / "workspaces",
    )


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _authority(
    root: Path,
    clock: _Clock,
    *,
    max_failures: int = 3,
    stable_reset_seconds: float = 30.0,
) -> DurableModelAutoRecoveryAuthority:
    directories = build_local_directory_authorities(_layout(root))
    return DurableModelAutoRecoveryAuthority(
        directories.layout,
        policy=ModelAutoRecoveryPolicy(
            max_failures=max_failures,
            window_seconds=300.0,
            base_backoff_seconds=2.0,
            max_backoff_seconds=30.0,
            stable_reset_seconds=stable_reset_seconds,
        ),
        clock=clock,
    )


def test_auto_recovery_circuit_survives_controller_restart(tmp_path: Path) -> None:
    clock = _Clock(100.0)
    digest = "a" * 64
    failure = "b" * 64
    authority = _authority(tmp_path, clock, max_failures=2)

    assert authority.authorize("deployment", digest).allow
    first = authority.record_failure("deployment", digest, failure)
    assert not first.circuit_open
    assert not authority.authorize("deployment", digest).allow

    clock.value = 102.0
    assert authority.authorize("deployment", digest).allow
    second = authority.record_failure("deployment", digest, failure)
    assert second.circuit_open

    # Reconstructing every controller object from the same durable root must not
    # erase the trip. Even aging the rolling timestamps out never auto-closes an
    # OPEN circuit.
    clock.value = 1000.0
    reopened = _authority(tmp_path, clock, max_failures=2)
    blocked = reopened.authorize("deployment", digest)
    assert not blocked.allow
    assert blocked.reason == "auto-recovery-circuit-open"

    reopened.reset("deployment", digest)
    assert reopened.authorize("deployment", digest).allow
    state = reopened.state("deployment", digest)
    assert state.manual_reset_count == 1
    assert state.circuit_trip_count == 1
    assert state.total_failures == 2


def test_stable_running_window_is_required_before_failure_budget_heals(
    tmp_path: Path,
) -> None:
    clock = _Clock(10.0)
    digest = "c" * 64
    failure = "d" * 64
    authority = _authority(
        tmp_path,
        clock,
        max_failures=1,
        stable_reset_seconds=20.0,
    )
    tripped = authority.record_failure("deployment", digest, failure)
    assert tripped.circuit_open

    # A manual start can make the service RUNNING while the automatic circuit
    # stays OPEN. One healthy observation is not sufficient to forgive history.
    clock.value = 12.0
    early = authority.record_running("deployment", digest)
    assert early.circuit_open
    assert early.running_since_epoch_s == 12.0

    clock.value = 31.9
    still_early = authority.record_running("deployment", digest)
    assert still_early.circuit_open

    clock.value = 32.0
    stable = authority.record_running("deployment", digest)
    assert not stable.circuit_open
    assert stable.attempt_timestamps == ()
    assert stable.last_failure_digest is None
    assert stable.same_failure_streak == 0
    assert authority.authorize("deployment", digest).allow


class _Catalog:
    def __init__(self, spec: ModelDeploymentSpec) -> None:
        self.spec = spec

    def deployments(self) -> tuple[ModelDeploymentSpec, ...]:
        return (self.spec,)

    def select(self, selector=None) -> tuple[ModelDeploymentSpec, ...]:
        del selector
        return (self.spec,)


class _FailingRuntime:
    def __init__(self, generation: ModelDeploymentGeneration) -> None:
        self._generation = generation
        self.start_calls = 0

    def generation(self, deployment_id: str) -> ModelDeploymentGeneration:
        assert deployment_id == self._generation.deployment_id
        return self._generation

    def status(self, deployment_id: str) -> ModelDeploymentStatus:
        return ModelDeploymentStatus(
            deployment_id,
            "service",
            ModelDesiredState.RUNNING,
            ModelRuntimeState.STOPPED,
            detail="applied-process-missing",
        )

    def start(self, generation: ModelDeploymentGeneration) -> ModelDeploymentStatus:
        assert generation == self._generation
        self.start_calls += 1
        raise RuntimeError("simulated repeated startup failure")

    def stop(self, generation):
        raise AssertionError("not used")

    def shutdown(self, generation):
        raise AssertionError("not used")

    def remove_deployment(self, generation):
        raise AssertionError("not used")


def test_fleet_reconcile_never_restarts_forever_after_budget_exhaustion(
    tmp_path: Path,
) -> None:
    clock = _Clock(100.0)
    desired_digest = "e" * 64
    generation = ModelDeploymentGeneration("deployment", desired_digest, None)
    runtime = _FailingRuntime(generation)
    spec = ModelDeploymentSpec(
        deployment_id="deployment",
        scope=PLATFORM_SCOPE,
        service_id="service",
        model_id="model",
        engine="test",
        executable="/bin/false",
        argv=("/bin/false",),
        cwd=tmp_path,
        desired_state=ModelDesiredState.RUNNING,
    )
    authority = _authority(tmp_path, clock, max_failures=2)
    fleet = ModelFleetRuntime(_Catalog(spec), runtime, authority)

    first = fleet.reconcile()[0]
    assert runtime.start_calls == 1
    assert "auto-recovery-failed" in first.detail

    # Backoff cycles observe state only; they do not call start again.
    second = fleet.reconcile()[0]
    assert runtime.start_calls == 1
    assert "auto-recovery-backoff" in second.detail

    clock.value = 102.0
    third = fleet.reconcile()[0]
    assert runtime.start_calls == 2
    assert "circuit-open" in third.detail

    # A new controller/fleet object over the same state root remains fenced.
    reopened = ModelFleetRuntime(
        _Catalog(spec),
        runtime,
        _authority(tmp_path, clock, max_failures=2),
    )
    fourth = reopened.reconcile()[0]
    assert runtime.start_calls == 2
    assert "auto-recovery-circuit-open" in fourth.detail

    assert reopened.reset_auto_recovery("deployment")
    fifth = reopened.reconcile()[0]
    assert runtime.start_calls == 3
    assert "auto-recovery-failed" in fifth.detail
