from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import Iterator


class ObservationEmissionMode(StrEnum):
    """Execution mode seen by the observation side-plane."""

    LIVE = "live"
    REPLAY = "replay"
    PROJECTION_REBUILD = "projection-rebuild"


_EMISSION_MODE: ContextVar[ObservationEmissionMode] = ContextVar(
    "noetrium_observation_emission_mode",
    default=ObservationEmissionMode.LIVE,
)


def current_observation_emission_mode() -> ObservationEmissionMode:
    return _EMISSION_MODE.get()


def operational_observation_enabled() -> bool:
    """Whether this context represents newly occurring operational work."""

    return current_observation_emission_mode() is ObservationEmissionMode.LIVE


@contextmanager
def observation_emission_scope(mode: ObservationEmissionMode) -> Iterator[None]:
    """Apply observation-only emission semantics to the current context."""

    if not isinstance(mode, ObservationEmissionMode):
        raise TypeError("observation emission mode must be ObservationEmissionMode")
    token = _EMISSION_MODE.set(mode)
    try:
        yield
    finally:
        _EMISSION_MODE.reset(token)


@contextmanager
def replay_observation_scope() -> Iterator[None]:
    with observation_emission_scope(ObservationEmissionMode.REPLAY):
        yield


@contextmanager
def projection_rebuild_observation_scope() -> Iterator[None]:
    with observation_emission_scope(ObservationEmissionMode.PROJECTION_REBUILD):
        yield


__all__ = [
    "ObservationEmissionMode",
    "current_observation_emission_mode",
    "observation_emission_scope",
    "operational_observation_enabled",
    "projection_rebuild_observation_scope",
    "replay_observation_scope",
]
