from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity

from .checkpoint import ParticipantCheckpoint
from .contracts import ParticipantRuntimeBinding
from .runtime import ParticipantRuntimeHandle


class ParticipantIdentityMismatch(RuntimeError):
    """Resolved endpoint or snapshot does not match the frozen runtime binding."""


@runtime_checkable
class ParticipantLifecycleAdapter(Protocol):
    """Runtime lifecycle bridge independent of Study/workflow orchestration.

    The adapter receives only the frozen participant runtime binding and resolved
    runtime handle. Experiment-specific specs must be translated before this boundary.
    """

    kind: str

    def frozen_component(self, binding: ParticipantRuntimeBinding) -> ComponentIdentity: ...
    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle: ...
    def actual_component(self, participant: ParticipantRuntimeHandle) -> ComponentIdentity: ...
    def validate(
        self,
        binding: ParticipantRuntimeBinding,
        participant: ParticipantRuntimeHandle,
    ) -> None: ...
    def open_session(
        self,
        participant: ParticipantRuntimeHandle,
        *,
        session_id: str,
        services: object,
    ) -> object: ...
    def close_session(self, session: object) -> None: ...
    def checkpoint(
        self,
        participant: ParticipantRuntimeHandle,
        session: object,
        *,
        session_id: str,
    ) -> ParticipantCheckpoint: ...
    def restore(
        self,
        participant: ParticipantRuntimeHandle,
        session: object,
        checkpoint: ParticipantCheckpoint,
        *,
        session_id: str,
    ) -> None: ...


class ParticipantLifecycleAdapterRegistry:
    def __init__(self, adapters: tuple[ParticipantLifecycleAdapter, ...]) -> None:
        self._by_kind = {adapter.kind: adapter for adapter in adapters}
        if len(self._by_kind) != len(adapters):
            raise ValueError("duplicate participant lifecycle adapter kind")

    def resolve(self, kind: str) -> ParticipantLifecycleAdapter:
        try:
            return self._by_kind[kind]
        except KeyError as exc:
            raise LookupError(f"no participant lifecycle adapter for kind={kind!r}") from exc

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_kind))


__all__ = [
    "ParticipantIdentityMismatch",
    "ParticipantLifecycleAdapter",
    "ParticipantLifecycleAdapterRegistry",
]
