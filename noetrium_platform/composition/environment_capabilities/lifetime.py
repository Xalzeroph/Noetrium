from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Mapping, Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.api import EnvironmentCapabilityDescriptor, EnvironmentSession
from noetrium_platform.capabilities.participant.capability.api import CapabilityDescriptor
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    ExecutionContext,
    canonical_digest,
    require_sha256,
)

from .capability import EnvironmentCapabilityProvider, environment_capability_descriptor_metadata


def environment_random_seed(
    context: ExecutionContext,
    namespace: str,
    *,
    scope: str,
) -> int:
    """Derive scientific environment randomness independent of treatment identity.

    Assignment-scoped environments are paired by Study assignment seed and
    repetition. Condition/treatment and physical lifetime identities are
    deliberately excluded so matched experimental conditions start from the
    exact same stochastic environment. Task scope adds only the task identity.
    """
    if not isinstance(context, ExecutionContext):
        raise TypeError("environment random seed requires ExecutionContext")
    if type(namespace) is not str or not namespace.strip():
        raise ValueError("environment random seed namespace must be non-empty")
    if scope not in {"assignment", "task"}:
        raise ValueError("environment random seed scope must be assignment or task")
    if context.assignment_seed is None:
        raise RuntimeError("environment random seed requires Study assignment seed")
    if scope == "task":
        task_id = context.task_id
        if type(task_id) is not str or not task_id.strip():
            raise RuntimeError("task-scoped environment seed requires task_id")
        task_id = task_id.strip()
    else:
        task_id = None
    pairing_id = context.participant_context.get("environment_pairing_id")
    if pairing_id is not None and (
        type(pairing_id) is not str or not pairing_id.strip()
    ):
        raise ValueError("environment_pairing_id must be non-empty text")
    setup = context.participant_context.get("environment_task_setup", {})
    world_pairing_key = None
    if isinstance(setup, Mapping):
        candidate = setup.get("world_pairing_key")
        if candidate is not None:
            if type(candidate) is not str or not candidate.strip():
                raise ValueError("environment world_pairing_key must be non-empty text")
            world_pairing_key = candidate.strip()
    # An explicit world_pairing_key defines scientific world identity
    # across distinct task records (for example Vanilla/Mirror matched pairs).
    # It must replace, not merely accompany, task_id; otherwise different task
    # ids silently produce different terrain despite an explicit pairing contract.
    task_seed_identity = world_pairing_key if world_pairing_key is not None else task_id
    digest = canonical_digest(
        {
            "schema": "noetrium.environment-random-seed.v3",
            "pairing_id": (
                pairing_id.strip()
                if isinstance(pairing_id, str)
                else context.study_id
            ),
            "assignment_seed": context.assignment_seed,
            "repetition": context.repetition,
            "task_seed_identity": task_seed_identity,
            "namespace": namespace.strip(),
        }
    )
    return int(digest[:16], 16)


@runtime_checkable
class EnvironmentLifetimeSessionControllerPort(Protocol):
    """Own exact EnvironmentSession lifecycle keyed by research lifetime identity."""

    @property
    def identity_digest(self) -> str: ...

    @property
    def effect_recovery_durability(self) -> str: ...

    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]: ...

    def prepare(self, context: ExecutionContext, control: ExecutionControlPort) -> None: ...

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
        sessions: EnvironmentLifetimeSessionControllerPort,
        *,
        capability_id: str = "environment.act",
        session_scope: str = "assignment",
    ) -> None:
        if not isinstance(sessions, EnvironmentLifetimeSessionControllerPort):
            raise TypeError(
                "lifetime-routed environment capability requires session controller"
            )
        if type(capability_id) is not str or not capability_id.strip():
            raise ValueError("lifetime-routed capability_id must be non-empty")
        require_sha256(
            sessions.identity_digest,
            "environment lifetime session controller identity",
        )
        if (
            type(session_scope) is not str
            or not session_scope.strip()
            or session_scope != session_scope.strip()
        ):
            raise ValueError(
                "environment session_scope must be canonical non-empty text"
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
                "session_controller_digest": sessions.identity_digest,
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
        if type(raw) is not str or not raw.strip() or raw != raw.strip():
            raise ValueError(
                "environment session scope must be canonical non-empty text"
            )
        return raw

    @staticmethod
    def _scope_identity(context: ExecutionContext, scope: str) -> str:
        explicit = context.participant_context.get("environment_scope_ids")
        if isinstance(explicit, Mapping):
            candidate = explicit.get(scope)
            if candidate is not None:
                if type(candidate) is not str or not candidate.strip():
                    raise ValueError(
                        f"environment scope identity for {scope!r} must be non-empty text"
                    )
                return candidate.strip()
        candidate = {
            "project": context.execution_tenant_id,
            "study": context.study_id,
            "experiment": context.experiment_id,
            "run": context.run_id,
            "branch": context.branch_id,
            "condition": context.condition_id,
            "operation": context.operation_id,
        }.get(scope)
        if type(candidate) is not str or not candidate.strip():
            raise ValueError(
                f"environment session scope {scope!r} requires an explicit scope identity"
            )
        return candidate.strip()

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
        if scope == "task":
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

        scope_id = self._scope_identity(context, scope)
        # Broader-than-assignment sessions belong to the outer execution, not
        # to an individual method/participant sub-run.  trace_id is stable
        # across those nested run_ids while remaining unique per top-level run.
        # Using context.run_id here fragments a study-scoped session into one
        # physical environment per method invocation.
        routed_id = "environment-scope:" + canonical_digest(
            {
                "schema": "noetrium.environment-session-scope.v2",
                "execution_trace_id": context.trace_id,
                "scope": scope,
                "scope_id": scope_id,
            }
        )
        participant_context = dict(context.participant_context)
        participant_context["environment_assignment_lifetime_id"] = lifetime_id
        participant_context["environment_session_scope_id"] = scope_id
        return replace(
            context,
            lifetime_id=routed_id,
            task_id=None,
            participant_context=participant_context,
        )

    @property
    def effect_recovery_durability(self) -> str:
        return self._sessions.effect_recovery_durability

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def prepare(
        self,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> None:
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("environment lifetime preparation requires ExecutionControlPort")
        control.checkpoint()
        if self._scope_for_context(context) == "task" and context.task_id is None:
            # Trial-level prewarm has no task identity. The caller may provide
            # the first task explicitly; otherwise opening is lazy.
            return
        self._sessions.prepare(self._routed_context(context), control)

    def session_for(self, context: ExecutionContext) -> EnvironmentCapabilityProvider:
        return EnvironmentCapabilityProvider(
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
    "EnvironmentLifetimeSessionControllerPort",
    "LifetimeRoutedEnvironmentCapability",
]
