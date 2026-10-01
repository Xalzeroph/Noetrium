from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.api import EnvironmentCapabilityDescriptor, EnvironmentSession
from noetrium_platform.capabilities.participant.capability.api import CapabilityDescriptor
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    ExecutionContext,
    canonical_digest,
    require_sha256,
)

from .action import EnvironmentSessionCapabilityAdapter, environment_capability_descriptor_metadata


@runtime_checkable
class EnvironmentLifetimeSessionAuthorityPort(Protocol):
    """Own exact EnvironmentSession lifecycle keyed by research lifetime identity."""

    @property
    def identity_digest(self) -> str: ...

    @property
    def effect_recovery_durability(self) -> str: ...

    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]: ...

    def prepare(self, context: ExecutionContext) -> None: ...

    def session_for(self, context: ExecutionContext) -> EnvironmentSession: ...

    def release(self, lifetime_id: str) -> None: ...

    def close(self) -> None: ...


class LifetimeRoutedEnvironmentCapability:
    """Resolve the Environment provider session for each execution lifetime.

    This object owns only lifetime/session routing. Generic capability mediation
    and effect prepare/execute/reconcile remain exclusively owned by
    StudyCapabilityRouter + CapabilityEffectExecutor.
    """

    def __init__(
        self,
        sessions: EnvironmentLifetimeSessionAuthorityPort,
        *,
        capability_id: str = "environment.act",
        session_scope: str = "assignment",
    ) -> None:
        if not isinstance(sessions, EnvironmentLifetimeSessionAuthorityPort):
            raise TypeError(
                "lifetime-routed environment capability requires session authority"
            )
        if type(capability_id) is not str or not capability_id.strip():
            raise ValueError("lifetime-routed capability_id must be non-empty")
        require_sha256(
            sessions.identity_digest,
            "environment lifetime session authority identity",
        )
        if session_scope not in {"assignment", "task"}:
            raise ValueError(
                "environment session_scope must be 'assignment' or 'task'"
            )
        self._sessions = sessions
        self._capability_id = capability_id.strip()
        self._session_scope = session_scope
        self._scope_lock = RLock()
        self._task_scopes_by_assignment: dict[str, set[str]] = {}
        self._descriptor = CapabilityDescriptor(
            capability_id=self._capability_id,
            interface_version="1",
            request_schema="noetrium.environment.action-capability.request.v1",
            result_schema="noetrium.environment.action-capability.result.v1",
            effect_class=EffectClass.RECONCILABLE,
            deterministic=False,
            metadata=environment_capability_descriptor_metadata(
                sessions.capability_descriptors()
            ),
        )
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.lifetime-routed-environment-capability.v2",
                "session_authority_digest": sessions.identity_digest,
                "capability_id": self._capability_id,
                "session_scope": self._session_scope,
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def session_scope(self) -> str:
        return self._session_scope

    def _scope_for_context(self, context: ExecutionContext) -> str:
        raw = context.participant_context.get(
            "environment_session_scope",
            self._session_scope,
        )
        scope = str(raw)
        if scope not in {"assignment", "task"}:
            raise ValueError(
                "environment session scope must be 'assignment' or 'task'"
            )
        return scope

    def _routed_context(self, context: ExecutionContext) -> ExecutionContext:
        lifetime_id = context.lifetime_id
        if type(lifetime_id) is not str or not lifetime_id.strip():
            raise ValueError(
                "environment capability requires ExecutionContext.lifetime_id"
            )
        lifetime_id = lifetime_id.strip()
        scope = self._scope_for_context(context)
        if scope == "assignment":
            # Assignment-scoped worlds must not accidentally inherit whichever
            # task happened to touch the provider first.
            return replace(context, task_id=None)
        task_id = context.task_id
        if type(task_id) is not str or not task_id.strip():
            raise ValueError(
                "task-scoped environment capability requires ExecutionContext.task_id"
            )
        routed_id = "environment-task:" + canonical_digest(
            {
                "assignment_lifetime_id": lifetime_id,
                "task_id": task_id.strip(),
            }
        )
        with self._scope_lock:
            self._task_scopes_by_assignment.setdefault(
                lifetime_id, set()
            ).add(routed_id)
        participant_context = dict(context.participant_context)
        participant_context["environment_assignment_lifetime_id"] = lifetime_id
        return replace(
            context,
            lifetime_id=routed_id,
            participant_context=participant_context,
        )

    @property
    def effect_recovery_durability(self) -> str:
        return self._sessions.effect_recovery_durability

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def prepare(self, context: ExecutionContext) -> None:
        if self._scope_for_context(context) == "task" and context.task_id is None:
            # Trial-level prewarm has no task identity. The caller may provide
            # the first task explicitly; otherwise opening is lazy.
            return
        self._sessions.prepare(self._routed_context(context))

    def session_for(self, context: ExecutionContext) -> EnvironmentSessionCapabilityAdapter:
        return EnvironmentSessionCapabilityAdapter(
            self._sessions.session_for(self._routed_context(context)),
            capability_id=self._capability_id,
        )

    def release_context(self, context: ExecutionContext) -> None:
        if self._scope_for_context(context) != "task":
            return
        routed = self._routed_context(context)
        routed_id = routed.lifetime_id
        assert routed_id is not None
        self._sessions.release(routed_id)
        assignment_id = context.lifetime_id
        assert assignment_id is not None
        with self._scope_lock:
            rows = self._task_scopes_by_assignment.get(assignment_id)
            if rows is not None:
                rows.discard(routed_id)
                if not rows:
                    self._task_scopes_by_assignment.pop(assignment_id, None)

    def release(self, lifetime_id: str) -> None:
        with self._scope_lock:
            routed_ids = tuple(
                sorted(self._task_scopes_by_assignment.pop(lifetime_id, set()))
            )
        if routed_ids:
            for routed_id in routed_ids:
                self._sessions.release(routed_id)
            return
        self._sessions.release(lifetime_id)

    def close(self) -> None:
        self._sessions.close()


__all__ = [
    "EnvironmentLifetimeSessionAuthorityPort",
    "LifetimeRoutedEnvironmentCapability",
]
