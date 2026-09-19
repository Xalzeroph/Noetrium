from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest
from noetrium_platform.capabilities.environment.embodied.api import (
    ActionKind,
    ActionSpec,
    EmbodimentKind,
    EmbodimentSpec,
    EpisodeSpec,
    SensorModality,
    SensorSpec,
)
from noetrium_platform.capabilities.environment.embodied.composition import (
    EmbodiedEnvironmentProviderAdapter,
)
from noetrium_platform.capabilities.environment.embodied.providers import (
    EmbodiedSimulatorEnvironment,
    SimulatorObservation,
    SimulatorStep,
)
from noetrium_platform.capabilities.environment.category.api import (
    EnvironmentCategoryStatus,
)
from noetrium_platform.capabilities.environment.category.runtime.catalog import (
    canonical_environment_implementations,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    ExecutionContext,
    canonical_digest,
)


class _Backend:
    def __init__(self) -> None:
        self.closed = False
        self.step_count = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "backend": "embodied-simulator-test",
            "implementation_revision": 1,
        })

    def reset(self, episode, context):
        assert episode.task_id == "pick"
        assert context.run_id == "run"
        return SimulatorObservation(
            raw_payload=b"reset-frame",
            normalized_payload={"frame_ref": "frame:0"},
            reward=0.0,
        )

    def step(self, command, context):
        self.step_count += 1
        return SimulatorStep(
            observation=SimulatorObservation(
                raw_payload=f"frame-{self.step_count}".encode(),
                normalized_payload={
                    "frame_ref": f"frame:{self.step_count}",
                },
                reward=1.0,
                success=True,
                terminated=True,
            ),
            action_status="applied",
            action_receipt={
                "command_id": command.command_id,
                "step": self.step_count,
            },
        )

    def close(self) -> None:
        self.closed = True


def _context() -> ExecutionContext:
    return ExecutionContext(
        "run",
        "trace",
        "span",
        task_id="pick",
    )


def _spec() -> EmbodimentSpec:
    return EmbodimentSpec(
        embodiment_id="sim-arm",
        revision="1",
        kind=EmbodimentKind.SIMULATED,
        sensors=(
            SensorSpec(
                sensor_id="rgb",
                modality=SensorModality.RGB,
                frame_id="camera",
                dtype="uint8",
                shape=(64, 64, 3),
            ),
        ),
        actions=(
            ActionSpec(
                action_id="pick_place",
                kind=ActionKind.CARTESIAN,
                dimensions=6,
            ),
        ),
    )


def test_generic_embodied_simulator_is_catalogued_available() -> None:
    descriptor = next(
        row
        for row in canonical_environment_implementations()
        if row.implementation_id == "embodied.simulator"
    )
    assert descriptor.status is EnvironmentCategoryStatus.AVAILABLE
    assert descriptor.backend_kind == "typed_simulator_backend"


def test_generic_embodied_simulator_composes_through_provider_adapter() -> None:
    backend = _Backend()
    ticks = iter(range(1, 20))
    environment = EmbodiedSimulatorEnvironment(
        spec=_spec(),
        backend=backend,
        environment_id="simulator.test",
        clock_ns=lambda: next(ticks),
    )
    provider = EmbodiedEnvironmentProviderAdapter(
        environment,
        environment_id="simulator.test",
        implementation_version="1",
        episode_factory=lambda session_id, spec: EpisodeSpec(
            episode_id=session_id,
            environment_id="simulator.test",
            embodiment_id=spec.embodiment_id,
            task_id="pick",
            seed=7,
        ),
    )
    session = provider.open_session(
        session_id="episode-1",
        services=object(),
    )

    initial = session.observe(_context())
    assert initial.payload["frame_ref"] == "frame:0"
    assert initial.payload["reward"] == 0.0
    assert initial.payload["done"] is False

    request = ActionRequest(
        "action-1",
        "pick_place",
        {"pose": [0.1, 0.2, 0.3, 0.0, 0.0, 1.0]},
        _context(),
    )
    result = session.act(request)

    assert result.accepted is True
    assert result.observation is not None
    assert result.observation.payload["frame_ref"] == "frame:1"
    assert result.observation.payload["reward"] == 1.0
    assert result.observation.payload["success"] is True
    assert result.observation.payload["done"] is True
    assert result.effect is not None
    assert result.effect.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert session.reconcile(result.effect, _context()) == result.effect

    session.close()
    assert backend.closed is True
