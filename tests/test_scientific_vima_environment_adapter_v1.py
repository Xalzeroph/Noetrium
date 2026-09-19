from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.environment.api import ActionRequest
from noetrium_platform.capabilities.environment.embodied.composition import (
    EmbodiedEnvironmentProviderAdapter,
)
from noetrium_platform.capabilities.environment.embodied.providers import (
    EmbodiedSimulatorEnvironment,
)
from noetrium_platform.evidence.artifact.content.providers import (
    CanonicalJsonTensorContentStore,
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from research.reproductions.vima_embodied.environment import (
    VimaBenchReset,
    VimaBenchSimulatorBackend,
    VimaBenchStep,
    VimaObservationEncoding,
    VimaPromptEncoding,
    vima_bench_embodiment_spec,
    vima_bench_episode,
    vima_initial_state_from_reset_observation,
)
from research.reproductions.vima_embodied.policy import VimaActionBounds


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="vima-env-run",
        trace_id="trace",
        span_id="span",
        study_id="vima",
        task_id="vima-bench:placement_generalization:visual_manipulation",
    )


def _store(root: Path) -> CanonicalJsonTensorContentStore:
    blob = DirectoryArtifactBlobStore(root / "blob")
    return CanonicalJsonTensorContentStore(
        blob,
        blob_store_identity_digest=canonical_digest({
            "provider": "vima-env-test-blob",
            "root": str((root / "blob").resolve()),
        }),
    )


class _Frontend:
    def __init__(self, store) -> None:
        self.store = store
        self.obs_calls = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "frontend": "camera-ready-fixture",
            "revision": 1,
        })

    def encode_prompt(self, *, prompt, prompt_assets, context):
        assert prompt == "put the object in the bowl"
        assert prompt_assets == {"obj": "fixture"}
        assert context.run_id == "vima-env-run"
        return VimaPromptEncoding(
            self.store.put(
                ((1.0, 0.0), (0.0, 1.0)),
                schema_id="vima.prompt-token.tensor.v1",
            ),
            self.store.put(
                (True, True),
                schema_id="vima.prompt-mask.tensor.v1",
            ),
        )

    def encode_observation(self, *, observation, meta_info, context):
        self.obs_calls += 1
        assert meta_info == {"n_objects": 2}
        assert context.run_id == "vima-env-run"
        value = float(self.obs_calls)
        return VimaObservationEncoding(
            self.store.put(
                ((value, 0.1), (value, 0.2)),
                schema_id="vima.observation-token.tensor.v1",
            ),
            self.store.put(
                (True, True),
                schema_id="vima.observation-mask.tensor.v1",
            ),
        )


class _Driver:
    def __init__(self, *, terminal_success: bool) -> None:
        self.terminal_success = terminal_success
        self.closed = False
        self.actions = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "driver": "vima-bench-fixture",
            "terminal_success": self.terminal_success,
            "revision": 1,
        })

    def reset(self, *, task_name, partition, seed, context):
        assert task_name == "visual_manipulation"
        assert partition == "placement_generalization"
        assert seed == 42
        assert context.run_id == "vima-env-run"
        return VimaBenchReset(
            raw_payload=b"reset-observation",
            observation={"rgb": "fixture", "segm": "fixture", "ee": 0},
            prompt="put the object in the bowl",
            prompt_assets={"obj": "fixture"},
            meta_info={"n_objects": 2},
            action_bounds=VimaActionBounds(
                low=(0.25, -0.5),
                high=(0.75, 0.5),
            ),
            oracle_max_steps=3,
        )

    def step(self, action, context):
        self.actions.append(action)
        assert context.run_id == "vima-env-run"
        return VimaBenchStep(
            raw_payload=b"step-observation",
            observation={"rgb": "fixture-2", "segm": "fixture-2", "ee": 1},
            reward=0.0,
            done=True,
            success=self.terminal_success,
            info={
                "prompt": "put the object in the bowl",
                "success": self.terminal_success,
                "failure": not self.terminal_success,
            },
        )

    def close(self):
        self.closed = True


def _session(tmp_path: Path, *, terminal_success: bool):
    store = _store(tmp_path)
    driver = _Driver(terminal_success=terminal_success)
    frontend = _Frontend(store)
    backend = VimaBenchSimulatorBackend(
        driver=driver,
        frontend=frontend,
    )
    environment = EmbodiedSimulatorEnvironment(
        spec=vima_bench_embodiment_spec(),
        backend=backend,
        environment_id="vima-bench-camera-ready",
    )
    provider = EmbodiedEnvironmentProviderAdapter(
        environment,
        environment_id="vima-bench-camera-ready",
        implementation_version="icml2023",
        episode_factory=lambda session_id, spec: vima_bench_episode(
            "vima-bench:placement_generalization:visual_manipulation",
            episode_id=session_id,
            seed=42,
        ),
    )
    return (
        provider.open_session(session_id="episode-1", services=object()),
        driver,
        frontend,
    )


def _action_request() -> ActionRequest:
    return ActionRequest(
        action_id="vima-action-1",
        action_type="embodied_action",
        payload={
            "task_id": "visual_manipulation",
            "step_index": 0,
            "action": {
                "pose0_position": (0.5, 0.0),
                "pose0_rotation": (0.0, 0.0, 0.0, 1.0),
                "pose1_position": (0.6, 0.1),
                "pose1_rotation": (0.0, 0.0, 0.0, 1.0),
            },
        },
        context=_context(),
    )


def test_vima_bench_backend_projects_reset_into_method_initial_state(
    tmp_path: Path,
) -> None:
    session, driver, frontend = _session(
        tmp_path,
        terminal_success=True,
    )
    observation = session.observe(_context())
    payload = observation.payload

    assert payload["partition"] == "placement_generalization"
    assert payload["task_name"] == "visual_manipulation"
    assert payload["seed"] == 42
    assert payload["oracle_max_steps"] == 3
    assert payload["done"] is False
    assert payload["success"] is False

    state = vima_initial_state_from_reset_observation(payload)
    assert state["task_id"] == "visual_manipulation"
    assert state["evaluation_partition"] == "placement_generalization"
    assert state["seed"] == 42
    assert state["max_steps"] == 5
    assert frontend.obs_calls == 1
    assert not driver.actions


def test_vima_bench_backend_preserves_done_vs_success_semantics(
    tmp_path: Path,
) -> None:
    session, driver, frontend = _session(
        tmp_path,
        terminal_success=False,
    )
    session.observe(_context())
    result = session.act(_action_request())

    assert result.accepted is True
    assert result.observation is not None
    assert result.observation.payload["done"] is True
    assert result.observation.payload["success"] is False
    assert result.observation.payload["reward"] == 0.0
    assert frontend.obs_calls == 2
    assert len(driver.actions) == 1

    session.close()
    assert driver.closed is True


def test_vima_bench_backend_emits_success_only_from_benchmark_info(
    tmp_path: Path,
) -> None:
    session, driver, _ = _session(
        tmp_path,
        terminal_success=True,
    )
    session.observe(_context())
    result = session.act(_action_request())

    assert result.observation is not None
    assert result.observation.payload["done"] is True
    assert result.observation.payload["success"] is True
    assert driver.actions[0].pose0_position == (0.5, 0.0)
