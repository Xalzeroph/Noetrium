from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.embodied.api import (
    ActionKind,
    ActionSpec,
    EmbodimentKind,
    EmbodimentSpec,
    EpisodeSpec,
    SensorModality,
    SensorSpec,
)
from noetrium_platform.capabilities.environment.embodied.providers import (
    EmbodiedSimulatorBackendPort,
    SimulatorObservation,
    SimulatorStep,
)
from noetrium_platform.evidence.artifact.content.api import TensorContentRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    canonical_digest,
    require_sha256,
    thaw_json,
)
from research.benchmarks.vima_bench import (
    VIMA_CAMERA_READY_EXECUTABLE_SEED,
    VIMA_PARTITION_TASKS,
)

from .policy import VimaActionBounds, VimaContinuousAction
from .source import (
    VIMA_BENCH_AUDITED_COMMIT,
    VIMA_POLICY_AUDITED_COMMIT,
)


_PROMPT_TOKEN_SCHEMA = "vima.prompt-token.tensor.v1"
_PROMPT_MASK_SCHEMA = "vima.prompt-mask.tensor.v1"
_OBSERVATION_TOKEN_SCHEMA = "vima.observation-token.tensor.v1"
_OBSERVATION_MASK_SCHEMA = "vima.observation-mask.tensor.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class VimaBenchReset:
    raw_payload: bytes
    observation: object
    prompt: object
    prompt_assets: object
    meta_info: object
    action_bounds: VimaActionBounds
    oracle_max_steps: int

    def __post_init__(self) -> None:
        if type(self.raw_payload) is not bytes:
            raise TypeError("VIMA-Bench reset raw_payload must be bytes")
        if not isinstance(self.action_bounds, VimaActionBounds):
            raise TypeError("VIMA-Bench reset requires VimaActionBounds")
        if type(self.oracle_max_steps) is not int or self.oracle_max_steps < 1:
            raise ValueError("VIMA-Bench oracle_max_steps must be positive")


@dataclass(frozen=True, slots=True)
class VimaBenchStep:
    raw_payload: bytes
    observation: object
    reward: float
    done: bool
    success: bool
    info: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.raw_payload) is not bytes:
            raise TypeError("VIMA-Bench step raw_payload must be bytes")
        if isinstance(self.reward, bool) or not isinstance(
            self.reward,
            (int, float),
        ):
            raise TypeError("VIMA-Bench reward must be numeric")
        if type(self.done) is not bool or type(self.success) is not bool:
            raise TypeError("VIMA-Bench done/success must be booleans")
        if not isinstance(self.info, Mapping):
            raise TypeError("VIMA-Bench info must be a mapping")


@runtime_checkable
class VimaBenchDriverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def reset(
        self,
        *,
        task_name: str,
        partition: str,
        seed: int,
        context: ExecutionContext,
    ) -> VimaBenchReset: ...

    def step(
        self,
        action: VimaContinuousAction,
        context: ExecutionContext,
    ) -> VimaBenchStep: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VimaPromptEncoding:
    token_ref: TensorContentRef
    mask_ref: TensorContentRef

    def __post_init__(self) -> None:
        if (
            not isinstance(self.token_ref, TensorContentRef)
            or self.token_ref.schema_id != _PROMPT_TOKEN_SCHEMA
        ):
            raise ValueError("VIMA prompt token ref schema drifted")
        if (
            not isinstance(self.mask_ref, TensorContentRef)
            or self.mask_ref.schema_id != _PROMPT_MASK_SCHEMA
        ):
            raise ValueError("VIMA prompt mask ref schema drifted")


@dataclass(frozen=True, slots=True)
class VimaObservationEncoding:
    token_ref: TensorContentRef
    mask_ref: TensorContentRef

    def __post_init__(self) -> None:
        if (
            not isinstance(self.token_ref, TensorContentRef)
            or self.token_ref.schema_id != _OBSERVATION_TOKEN_SCHEMA
        ):
            raise ValueError("VIMA observation token ref schema drifted")
        if (
            not isinstance(self.mask_ref, TensorContentRef)
            or self.mask_ref.schema_id != _OBSERVATION_MASK_SCHEMA
        ):
            raise ValueError("VIMA observation mask ref schema drifted")


@runtime_checkable
class VimaCameraReadyFrontendPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def encode_prompt(
        self,
        *,
        prompt: object,
        prompt_assets: object,
        context: ExecutionContext,
    ) -> VimaPromptEncoding: ...

    def encode_observation(
        self,
        *,
        observation: object,
        meta_info: object,
        context: ExecutionContext,
    ) -> VimaObservationEncoding: ...


@dataclass(frozen=True, slots=True)
class VimaBenchmarkTaskIdentity:
    partition: str
    task_name: str

    def __post_init__(self) -> None:
        partition = _text(self.partition, "VIMA partition")
        task_name = _text(self.task_name, "VIMA task_name")
        expected = VIMA_PARTITION_TASKS.get(partition)
        if expected is None or task_name not in expected:
            raise ValueError(
                f"VIMA task is not in benchmark partition: "
                f"{partition}:{task_name}"
            )
        object.__setattr__(self, "partition", partition)
        object.__setattr__(self, "task_name", task_name)

    @property
    def benchmark_task_id(self) -> str:
        return f"vima-bench:{self.partition}:{self.task_name}"


def parse_vima_benchmark_task_id(task_id: str) -> VimaBenchmarkTaskIdentity:
    task_id = _text(task_id, "VIMA benchmark task_id")
    parts = task_id.split(":")
    if len(parts) != 3 or parts[0] != "vima-bench":
        raise ValueError(
            "VIMA benchmark task_id must be "
            "vima-bench:{partition}:{task_name}"
        )
    return VimaBenchmarkTaskIdentity(parts[1], parts[2])


def vima_bench_episode(
    benchmark_task_id: str,
    *,
    episode_id: str,
    seed: int = VIMA_CAMERA_READY_EXECUTABLE_SEED,
) -> EpisodeSpec:
    identity = parse_vima_benchmark_task_id(benchmark_task_id)
    if type(seed) is not int:
        raise TypeError("VIMA benchmark seed must be an integer")
    return EpisodeSpec(
        episode_id=_text(episode_id, "VIMA episode_id"),
        environment_id="vima-bench-camera-ready",
        embodiment_id="vima-bench-ur5",
        task_id=identity.benchmark_task_id,
        seed=seed,
        scenario_id=identity.partition,
        policy_id="vima-camera-ready",
        metadata={
            "partition": identity.partition,
            "task_name": identity.task_name,
            "benchmark_commit": VIMA_BENCH_AUDITED_COMMIT,
            "policy_commit": VIMA_POLICY_AUDITED_COMMIT,
        },
    )


def vima_bench_embodiment_spec() -> EmbodimentSpec:
    return EmbodimentSpec(
        embodiment_id="vima-bench-ur5",
        revision=VIMA_BENCH_AUDITED_COMMIT[:12],
        kind=EmbodimentKind.SIMULATED,
        sensors=(
            SensorSpec(
                "rgb-front",
                SensorModality.RGB,
                "camera-front",
                "uint8",
                metadata={"view": "front"},
            ),
            SensorSpec(
                "rgb-top",
                SensorModality.RGB,
                "camera-top",
                "uint8",
                metadata={"view": "top"},
            ),
            SensorSpec(
                "segm-front",
                "segmentation",
                "camera-front",
                "uint8",
                metadata={"view": "front"},
            ),
            SensorSpec(
                "segm-top",
                "segmentation",
                "camera-top",
                "uint8",
                metadata={"view": "top"},
            ),
            SensorSpec(
                "end-effector",
                SensorModality.PROPRIOCEPTION,
                "ur5-ee",
                "int64",
                shape=(1,),
            ),
        ),
        actions=(
            ActionSpec(
                "embodied_action",
                ActionKind.CARTESIAN,
                12,
                metadata={
                    "layout": (
                        "pose0_position[2],pose0_rotation[4],"
                        "pose1_position[2],pose1_rotation[4]"
                    ),
                },
            ),
        ),
        metadata={
            "benchmark_commit": VIMA_BENCH_AUDITED_COMMIT,
            "modalities": "rgb,segm,ee",
            "views": "front,top",
            "hide_arm_rgb": "false-camera-ready-example",
        },
    )


class VimaBenchSimulatorBackend(EmbodiedSimulatorBackendPort):
    """Camera-ready VIMA-Bench semantics over generic simulator mechanics."""

    def __init__(
        self,
        *,
        driver: VimaBenchDriverPort,
        frontend: VimaCameraReadyFrontendPort,
    ) -> None:
        if not isinstance(driver, VimaBenchDriverPort):
            raise TypeError("VIMA backend requires VimaBenchDriverPort")
        if not isinstance(frontend, VimaCameraReadyFrontendPort):
            raise TypeError(
                "VIMA backend requires VimaCameraReadyFrontendPort"
            )
        require_sha256(
            driver.identity_digest,
            "VIMA-Bench driver identity_digest",
        )
        require_sha256(
            frontend.identity_digest,
            "VIMA frontend identity_digest",
        )
        self._driver = driver
        self._frontend = frontend
        self._active: VimaBenchmarkTaskIdentity | None = None
        self._meta_info: object = None
        self._step_index = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "benchmark_commit": VIMA_BENCH_AUDITED_COMMIT,
            "policy_commit": VIMA_POLICY_AUDITED_COMMIT,
            "driver_identity_digest": self._driver.identity_digest,
            "frontend_identity_digest": self._frontend.identity_digest,
            "reset_fault_tolerance": "driver-owned-camera-ready",
            "episode_budget": "oracle-max-steps-plus-two",
            "implementation_revision": 1,
        })

    def reset(
        self,
        episode: EpisodeSpec,
        context: ExecutionContext,
    ) -> SimulatorObservation:
        if not isinstance(episode, EpisodeSpec):
            raise TypeError("VIMA backend reset requires EpisodeSpec")
        identity = parse_vima_benchmark_task_id(episode.task_id)
        if episode.seed is None:
            raise ValueError("VIMA benchmark episode requires explicit seed")
        if episode.scenario_id and episode.scenario_id != identity.partition:
            raise ValueError("VIMA episode partition identity drifted")
        reset = self._driver.reset(
            task_name=identity.task_name,
            partition=identity.partition,
            seed=episode.seed,
            context=context,
        )
        if not isinstance(reset, VimaBenchReset):
            raise TypeError("VIMA driver reset must return VimaBenchReset")
        prompt = self._frontend.encode_prompt(
            prompt=reset.prompt,
            prompt_assets=reset.prompt_assets,
            context=context,
        )
        observation = self._frontend.encode_observation(
            observation=reset.observation,
            meta_info=reset.meta_info,
            context=context,
        )
        if not isinstance(prompt, VimaPromptEncoding):
            raise TypeError("VIMA frontend returned invalid prompt encoding")
        if not isinstance(observation, VimaObservationEncoding):
            raise TypeError(
                "VIMA frontend returned invalid observation encoding"
            )

        self._active = identity
        self._meta_info = reset.meta_info
        self._step_index = 0
        return SimulatorObservation(
            raw_payload=reset.raw_payload,
            normalized_payload={
                "benchmark_task_id": identity.benchmark_task_id,
                "partition": identity.partition,
                "task_name": identity.task_name,
                "seed": episode.seed,
                "prompt_token_ref": prompt.token_ref.payload(),
                "prompt_mask_ref": prompt.mask_ref.payload(),
                "vima_observation_token_ref": (
                    observation.token_ref.payload()
                ),
                "vima_observation_mask_ref": observation.mask_ref.payload(),
                "action_bounds": reset.action_bounds.payload(),
                "oracle_max_steps": reset.oracle_max_steps,
                "benchmark_commit": VIMA_BENCH_AUDITED_COMMIT,
                "policy_commit": VIMA_POLICY_AUDITED_COMMIT,
            },
            reward=0.0,
            success=False,
            terminated=False,
            truncated=False,
            metadata={
                "driver_identity_digest": self._driver.identity_digest,
                "frontend_identity_digest": self._frontend.identity_digest,
            },
        )

    def step(
        self,
        command,
        context: ExecutionContext,
    ) -> SimulatorStep:
        if self._active is None:
            raise RuntimeError("VIMA backend must reset before step")
        normalized = thaw_json(command.normalized_payload)
        if not isinstance(normalized, dict):
            raise TypeError("VIMA action payload must be an object")
        action_value = normalized.get("action")
        if not isinstance(action_value, Mapping):
            raise TypeError("VIMA action payload requires action object")
        action = VimaContinuousAction(
            pose0_position=tuple(action_value.get("pose0_position", ())),
            pose0_rotation=tuple(action_value.get("pose0_rotation", ())),
            pose1_position=tuple(action_value.get("pose1_position", ())),
            pose1_rotation=tuple(action_value.get("pose1_rotation", ())),
        )
        declared_task = normalized.get("task_id")
        if declared_task is not None and declared_task != self._active.task_name:
            raise ValueError("VIMA method task identity drifted")
        declared_step = normalized.get("step_index")
        if type(declared_step) is not int or declared_step != self._step_index:
            raise ValueError("VIMA method/environment step index drifted")

        step = self._driver.step(action, context)
        if not isinstance(step, VimaBenchStep):
            raise TypeError("VIMA driver step must return VimaBenchStep")
        observation = self._frontend.encode_observation(
            observation=step.observation,
            meta_info=self._meta_info,
            context=context,
        )
        if not isinstance(observation, VimaObservationEncoding):
            raise TypeError(
                "VIMA frontend returned invalid observation encoding"
            )
        self._step_index += 1
        return SimulatorStep(
            observation=SimulatorObservation(
                raw_payload=step.raw_payload,
                normalized_payload={
                    "benchmark_task_id": self._active.benchmark_task_id,
                    "partition": self._active.partition,
                    "task_name": self._active.task_name,
                    "step_index": self._step_index,
                    "vima_observation_token_ref": (
                        observation.token_ref.payload()
                    ),
                    "vima_observation_mask_ref": (
                        observation.mask_ref.payload()
                    ),
                    "benchmark_info_digest": canonical_digest(
                        dict(step.info)
                    ),
                },
                reward=float(step.reward),
                success=step.success,
                terminated=step.done,
                truncated=False,
                metadata={
                    "driver_identity_digest": self._driver.identity_digest,
                    "frontend_identity_digest": (
                        self._frontend.identity_digest
                    ),
                },
            ),
            action_status="applied",
            action_receipt={
                "benchmark_commit": VIMA_BENCH_AUDITED_COMMIT,
                "task_id": self._active.task_name,
                "partition": self._active.partition,
                "step_index": self._step_index,
                "success": step.success,
                "done": step.done,
            },
        )

    def close(self) -> None:
        self._driver.close()
        self._active = None
        self._meta_info = None


def vima_initial_state_from_reset_observation(
    payload: object,
) -> JsonObject:
    if not isinstance(payload, Mapping):
        raise TypeError("VIMA reset observation payload must be an object")
    task_name = _text(payload.get("task_name"), "VIMA reset task_name")
    partition = _text(payload.get("partition"), "VIMA reset partition")
    seed = payload.get("seed")
    oracle_max_steps = payload.get("oracle_max_steps")
    if type(seed) is not int:
        raise TypeError("VIMA reset seed must be an integer")
    if type(oracle_max_steps) is not int or oracle_max_steps < 1:
        raise ValueError("VIMA reset oracle_max_steps must be positive")

    prompt_token = TensorContentRef.from_payload(
        dict(payload["prompt_token_ref"])
    )
    prompt_mask = TensorContentRef.from_payload(
        dict(payload["prompt_mask_ref"])
    )
    observation_token = TensorContentRef.from_payload(
        dict(payload["vima_observation_token_ref"])
    )
    observation_mask = TensorContentRef.from_payload(
        dict(payload["vima_observation_mask_ref"])
    )
    bounds = VimaActionBounds.from_payload(payload.get("action_bounds"))

    from .program import vima_initial_state

    return vima_initial_state(
        task_id=task_name,
        evaluation_partition=partition,
        seed=seed,
        oracle_max_steps=oracle_max_steps,
        prompt_token_ref=prompt_token,
        prompt_mask_ref=prompt_mask,
        initial_observation_token_ref=observation_token,
        initial_observation_mask_ref=observation_mask,
        action_bounds=bounds,
    )


__all__ = [
    "VimaBenchDriverPort",
    "VimaBenchReset",
    "VimaBenchSimulatorBackend",
    "VimaBenchStep",
    "VimaBenchmarkTaskIdentity",
    "VimaCameraReadyFrontendPort",
    "VimaObservationEncoding",
    "VimaPromptEncoding",
    "parse_vima_benchmark_task_id",
    "vima_bench_embodiment_spec",
    "vima_bench_episode",
    "vima_initial_state_from_reset_observation",
]
