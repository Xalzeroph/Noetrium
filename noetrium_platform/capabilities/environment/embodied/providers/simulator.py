from __future__ import annotations

import time
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    canonical_bytes,
    canonical_digest,
    require_sha256,
    thaw_json,
)

from ..api import (
    EmbodiedActionCommand,
    EmbodiedEnvironmentPort,
    EmbodiedEvent,
    EmbodiedEventKind,
    EmbodiedSimulatorBackendPort,
    EmbodimentSpec,
    EpisodeSpec,
    SimulatorObservation,
    SimulatorStep,
)


class EmbodiedSimulatorEnvironment(EmbodiedEnvironmentPort):
    """Generic embodied simulator mechanics over a typed backend.

    Paper/task-specific observation construction and action meaning remain in
    the backend or downstream reproduction. This class owns only eventization,
    sequencing, identity binding, and fail-closed episode consistency.
    """

    def __init__(
        self,
        *,
        spec: EmbodimentSpec,
        backend: EmbodiedSimulatorBackendPort,
        environment_id: str,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not isinstance(spec, EmbodimentSpec):
            raise TypeError("simulator environment requires EmbodimentSpec")
        if not isinstance(backend, EmbodiedSimulatorBackendPort):
            raise TypeError("simulator environment requires EmbodiedSimulatorBackendPort")
        if type(environment_id) is not str or not environment_id.strip():
            raise ValueError("simulator environment_id is required")
        require_sha256(
            backend.identity_digest,
            "embodied simulator backend identity_digest",
        )
        if not callable(clock_ns):
            raise TypeError("simulator clock_ns must be callable")
        self._spec = spec
        self._backend = backend
        self._environment_id = environment_id.strip()
        self._clock_ns = clock_ns
        self._episode: EpisodeSpec | None = None
        self._event_sequence = 0
        self._step_index = 0
        self._closed = False

    @property
    def spec(self) -> EmbodimentSpec:
        return self._spec

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "environment_id": self._environment_id,
            "embodiment_spec_digest": self._spec.spec_digest,
            "backend_identity_digest": self._backend.identity_digest,
            "implementation_revision": 1,
        })

    def reset(
        self,
        episode: EpisodeSpec,
        context: ExecutionContext,
    ) -> tuple[EmbodiedEvent, ...]:
        self._ensure_open()
        if not isinstance(episode, EpisodeSpec):
            raise TypeError("simulator reset requires EpisodeSpec")
        if episode.embodiment_id != self._spec.embodiment_id:
            raise ValueError("episode embodiment identity drifted")
        observation = self._backend.reset(episode, context)
        if not isinstance(observation, SimulatorObservation):
            raise TypeError("simulator backend reset must return SimulatorObservation")
        self._episode = episode
        self._event_sequence = 0
        self._step_index = 0
        return (
            self._event(
                EmbodiedEventKind.EPISODE_START,
                raw_payload=canonical_bytes(episode.record()),
                normalized_payload={
                    "episode": episode.record(),
                    "backend_identity_digest": self._backend.identity_digest,
                },
                status="ok",
            ),
            self._observation_event(observation),
        )

    def step(
        self,
        command: EmbodiedActionCommand,
        context: ExecutionContext,
    ) -> tuple[EmbodiedEvent, ...]:
        self._ensure_open()
        episode = self._require_episode()
        if not isinstance(command, EmbodiedActionCommand):
            raise TypeError("simulator step requires EmbodiedActionCommand")
        if command.episode_id != episode.episode_id:
            raise ValueError("simulator action episode identity drifted")
        step = self._backend.step(command, context)
        if not isinstance(step, SimulatorStep):
            raise TypeError("simulator backend step must return SimulatorStep")
        self._step_index += 1
        action_event = self._event(
            EmbodiedEventKind.ACTION_RESULT,
            raw_payload=command.raw_payload,
            normalized_payload={
                "command_id": command.command_id,
                "action_id": command.action_id,
                "sequence": command.sequence,
                "action_receipt": thaw_json(step.action_receipt),
            },
            status=step.action_status,
            action_id=command.action_id,
            outcome=step.action_status,
        )
        observation_event = self._observation_event(step.observation)
        return (action_event, observation_event)

    def close(self) -> None:
        if not self._closed:
            self._backend.close()
            self._closed = True

    def _observation_event(
        self,
        observation: SimulatorObservation,
    ) -> EmbodiedEvent:
        payload = dict(thaw_json(observation.normalized_payload))
        if observation.decision_payload is not None:
            payload["decision_view"] = thaw_json(observation.decision_payload)
        payload.update({
            "reward": observation.reward,
            "success": observation.success,
            "done": observation.terminated or observation.truncated,
            "terminated": observation.terminated,
            "truncated": observation.truncated,
            "backend_metadata": thaw_json(observation.metadata),
        })
        return self._event(
            EmbodiedEventKind.OBSERVATION,
            raw_payload=observation.raw_payload,
            normalized_payload=payload,
            status=observation.status,
            terminated=observation.terminated,
            truncated=observation.truncated,
            outcome=("success" if observation.success else None),
        )

    def _event(
        self,
        kind: EmbodiedEventKind,
        *,
        raw_payload: bytes,
        normalized_payload: JsonObject,
        status: str,
        action_id: str = "",
        outcome: str | None = None,
        terminated: bool = False,
        truncated: bool = False,
    ) -> EmbodiedEvent:
        episode = self._require_episode()
        self._event_sequence += 1
        event_id = (
            f"{episode.episode_id}:"
            f"{self._event_sequence}:"
            f"{kind.value}"
        )
        return EmbodiedEvent(
            event_id=event_id,
            episode_id=episode.episode_id,
            sequence=self._event_sequence,
            kind=kind,
            event_time_ns=int(self._clock_ns()),
            raw_payload=raw_payload,
            normalized_payload=normalized_payload,
            source_id=self._backend.identity_digest,
            embodiment_id=self._spec.embodiment_id,
            environment_id=episode.environment_id,
            task_id=episode.task_id,
            step_index=self._step_index,
            action_id=action_id,
            status=status,
            outcome=outcome,
            terminated=terminated,
            truncated=truncated,
            dimensions={
                "environment_identity_digest": self.identity_digest,
            },
        )

    def _require_episode(self) -> EpisodeSpec:
        if self._episode is None:
            raise RuntimeError("simulator environment must be reset before use")
        return self._episode

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("simulator environment is closed")


__all__ = [
    "EmbodiedSimulatorBackendPort",
    "EmbodiedSimulatorEnvironment",
    "SimulatorObservation",
    "SimulatorStep",
]
