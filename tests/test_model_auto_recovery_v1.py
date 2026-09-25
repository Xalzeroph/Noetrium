from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
    max_attempts: int = 3,
    stable_reset_seconds: float = 30.0,
    attempt_timeout_seconds: float = 10.0,
) -> DurableModelAutoRecoveryAuthority:
    directories = build_local_directory_authorities(_layout(root))
    return DurableModelAutoRecoveryAuthority(
        directories.layout,
        policy=ModelAutoRecoveryPolicy(
            max_attempts=max_attempts,
            window_seconds=300.0,
            base_backoff_seconds=2.0,
            max_backoff_seconds=30.0,
            stable_reset_seconds=stable_reset_seconds,
            attempt_timeout_seconds=attempt_timeout_seconds,
        ),
        clock=clock,
    )


def _fail_claim(
    authority: DurableModelAutoRecoveryAuthority,
    deployment_id: str,
    digest: str,
    failure: str,
):
    claim = authority.claim_attempt(deployment_id, digest)
    assert claim.allow
    assert claim.claim_id is not None
    return authority.record_failure(
        deployment_id,
        digest,
        claim.claim_id,
        failure,
    )


def test_auto_recovery_circuit_survives_controller_restart(tmp_path: Path) -> None:
    clock = _Clock(100.0)
    digest = "a" * 64
    failure = "b" * 64
    authority = _authority(tmp_path, clock, max_attempts=2)

    first = _fail_claim(authority, "deployment", digest, failure)
    assert not first.circuit_open
    blocked = authority.claim_attempt("deployment", digest)
    assert not blocked.allow
    assert blocked.reason == "auto-recovery-backoff"

    clock.value = 102.0
    second = _fail_claim(authority, "deployment", digest, failure)
    assert second.circuit_open

    clock.value = 1000.0
    reopened = _authority(tmp_path, clock, max_attempts=2)
    blocked = reopened.claim_attempt("deployment", digest)
    assert not blocked.allow
    assert blocked.reason == "auto-recovery-circuit-open"

    reopened.reset("deployment", digest)
    claim = reopened.claim_attempt("deployment", digest)
    assert claim.allow
    assert claim.claim_id is not None
    state = reopened.state("deployment", digest)
    assert state.manual_reset_count == 1
    assert state.circuit_trip_count == 1
    assert state.total_attempts == 3
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
        max_attempts=1,
        stable_reset_seconds=20.0,
    )
    tripped = _fail_claim(authority, "deployment", digest, failure)
    assert tripped.circuit_open

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
    claim = authority.claim_attempt("deployment", digest)
    assert claim.allow


def test_concurrent_controllers_cannot_claim_same_restart_attempt(
    tmp_path: Path,
) -> None:
    clock = _Clock(50.0)
    digest = "1" * 64
    left = _authority(tmp_path, clock, max_attempts=3)
    right = _authority(tmp_path, clock, max_attempts=3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = tuple(
            pool.map(
                lambda authority: authority.claim_attempt("deployment", digest),
                (left, right),
            )
        )

    allowed = tuple(row for row in decisions if row.allow)
    blocked = tuple(row for row in decisions if not row.allow)
    assert len(allowed) == 1
    assert len(blocked) == 1
    assert blocked[0].reason == "auto-recovery-attempt-inflight"
    state = left.state("deployment", digest)
    assert state.total_attempts == 1
    assert len(state.attempt_timestamps) == 1


def test_crash_after_claim_consumes_budget_and_eventually_opens_circuit(
    tmp_path: Path,
) -> None:
    clock = _Clock(100.0)
    digest = "2" * 64
    authority = _authority(
        tmp_path,
        clock,
        max_attempts=2,
        attempt_timeout_seconds=5.0,
    )

    first = authority.claim_attempt("deployment", digest)
    assert first.allow
    assert first.claim_id is not None

    # Simulate SIGKILL before success/failure publication.
    clock.value = 102.0
    inflight = _authority(
        tmp_path,
        clock,
        max_attempts=2,
        attempt_timeout_seconds=5.0,
    ).claim_attempt("deployment", digest)
    assert not inflight.allow
    assert inflight.reason == "auto-recovery-attempt-inflight"

    clock.value = 106.0
    second_authority = _authority(
        tmp_path,
        clock,
        max_attempts=2,
        attempt_timeout_seconds=5.0,
    )
    second = second_authority.claim_attempt("deployment", digest)
    assert second.allow
    assert second.claim_id is not None
    assert second_authority.state("deployment", digest).total_attempts == 2

    # Crash again. Once the second durable claim expires, no third automatic
    # restart is allowed even though neither crashed controller recorded failure.
    clock.value = 112.0
    terminal = _authority(
        tmp_path,
        clock,
        max_attempts=2,
        attempt_timeout_seconds=5.0,
    ).claim_attempt("deployment", digest)
    assert not terminal.allow
    assert terminal.reason == "auto-recovery-attempt-budget-exhausted"
    assert terminal.state.circuit_open


def test_manual_reset_refuses_to_race_active_auto_recovery(
    tmp_path: Path,
) -> None:
    clock = _Clock(10.0)
    digest = "3" * 64
    authority = _authority(tmp_path, clock, attempt_timeout_seconds=5.0)
    claim = authority.claim_attempt("deployment", digest)
    assert claim.allow

    try:
        authority.reset("deployment", digest)
    except RuntimeError as exc:
        assert "attempt is active" in str(exc)
    else:
        raise AssertionError("manual reset raced an active auto-recovery claim")

    clock.value = 16.0
    reset = authority.reset("deployment", digest)
    assert reset.manual_reset_count == 1
    assert reset.active_claim_id is None


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
    authority = _authority(tmp_path, clock, max_attempts=2)
    fleet = ModelFleetRuntime(_Catalog(spec), runtime, authority)

    first = fleet.reconcile()[0]
    assert runtime.start_calls == 1
    assert "auto-recovery-failed" in first.detail

    second = fleet.reconcile()[0]
    assert runtime.start_calls == 1
    assert "auto-recovery-backoff" in second.detail

    clock.value = 102.0
    third = fleet.reconcile()[0]
    assert runtime.start_calls == 2
    assert "circuit-open" in third.detail

    reopened = ModelFleetRuntime(
        _Catalog(spec),
        runtime,
        _authority(tmp_path, clock, max_attempts=2),
    )
    fourth = reopened.reconcile()[0]
    assert runtime.start_calls == 2
    assert "auto-recovery-circuit-open" in fourth.detail

    assert reopened.reset_auto_recovery("deployment")
    fifth = reopened.reconcile()[0]
    assert runtime.start_calls == 3
    assert "auto-recovery-failed" in fifth.detail
