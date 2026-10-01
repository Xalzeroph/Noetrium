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
from noetrium_platform.capabilities.environment.embodied.composition import EmbodiedEnvironmentProviderAdapter
from noetrium_platform.capabilities.environment.embodied.composition.provider_adapter import _EmbodiedSessionAdapter
from noetrium_platform.capabilities.environment.embodied.api import EmbodiedEvent, EmbodiedEventKind
from noetrium_platform.foundation.kernel.kernel import thaw_json
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
            normalized_payload={
                "frame_ref": "frame:0",
                "backend_debug": {"tensor_count": 17},
            },
            decision_payload={
                "goal": "pick",
                "frame_ref": "frame:0",
                "proprioception": {"gripper_open": True},
            },
            reward=0.0,
            metadata={"backend_trace": "reset-secret"},
        )

    def step(self, command, context):
        self.step_count += 1
        return SimulatorStep(
            observation=SimulatorObservation(
                raw_payload=f"frame-{self.step_count}".encode(),
                normalized_payload={
                    "frame_ref": f"frame:{self.step_count}",
                    "backend_debug": {"tensor_count": 19},
                },
                decision_payload={
                    "goal": "pick",
                    "frame_ref": f"frame:{self.step_count}",
                    "proprioception": {"gripper_open": False},
                },
                reward=1.0,
                success=True,
                metadata={"backend_trace": "step-secret"},
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


def test_embodied_backend_decision_payload_is_separate_from_authoritative_observation() -> None:
    backend = _Backend()
    environment = EmbodiedSimulatorEnvironment(
        spec=_spec(),
        backend=backend,
        environment_id="sim",
        clock_ns=lambda: 1,
    )
    events = environment.reset(
        EpisodeSpec("episode", "sim", "sim-arm", "pick"),
        _context(),
    )
    observation = events[-1]
    payload = observation.normalized_payload
    assert payload["frame_ref"] == "frame:0"
    assert payload["backend_debug"]["tensor_count"] == 17
    view = payload["decision_view"]
    assert view["goal"] == "pick"
    assert view["frame_ref"] == "frame:0"
    assert "backend_debug" not in view


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
    assert initial.payload["backend_metadata"]["backend_trace"] == "reset-secret"
    initial_view = initial.payload["decision_view"]
    assert initial_view["kind"] == "embodied_decision_view.v1"
    assert initial_view["observation"]["frame_ref"] == "frame:0"
    assert initial_view["observation"]["reward"] == 0.0
    assert "backend_metadata" not in initial_view["observation"]
    assert "event_id" not in initial_view["observation"]
    assert "raw_payload_sha256" not in initial_view["observation"]

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
    result_view = result.observation.payload["decision_view"]
    assert result_view["observation"]["frame_ref"] == "frame:1"
    assert result_view["observation"]["success"] is True
    assert result_view["observation"]["done"] is True
    assert "backend_metadata" not in result_view["observation"]
    assert result.effect is not None
    assert result.effect.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert session.reconcile(result.effect, _context()) == result.effect

    session.close()
    assert backend.closed is True


def test_embodied_backend_specific_decision_view_is_authoritative_for_model_context() -> None:
    event = EmbodiedEvent(
        event_id="e:1",
        episode_id="e",
        sequence=1,
        kind=EmbodiedEventKind.OBSERVATION,
        event_time_ns=1,
        raw_payload=b"raw-frame",
        normalized_payload={
            "pixels_ref": "artifact://frame/full",
            "objects": [{"id": i, "label": "cube"} for i in range(100)],
            "decision_view": {
                "pixels_ref": "artifact://frame/model",
                "objects": [{"id": 3, "label": "target"}],
            },
            "reward": 0.5,
            "success": False,
            "done": False,
            "backend_metadata": {"renderer": "internal"},
        },
        source_id="backend",
        embodiment_id="arm",
        environment_id="sim",
        task_id="pick",
    )
    view = _EmbodiedSessionAdapter._decision_view(
        event,
        dict(thaw_json(event.normalized_payload)),
    )
    assert view is not None
    observation = view["observation"]
    assert observation["pixels_ref"] == "artifact://frame/model"
    assert observation["objects"] == [{"id": 3, "label": "target"}]
    assert observation["reward"] == 0.5
    assert observation["done"] is False
    assert "backend_metadata" not in observation
