from __future__ import annotations

from dataclasses import replace
import time

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.governance.release.api import ReleasePinStorePort
from noetrium_platform.infrastructure.lifecycle.host.bootstrap.api import (
    ServerBootstrapBlocked,
    ServerBootstrapPhase,
    ServerBootstrapState,
    ServerBootstrapStatePort,
    ServerBootstrapTransactionReport,
)
from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionDrift,
    PersistentSessionEffectUncertain,
    PersistentSessionRuntimePort,
    PersistentSessionSpec,
)


class ServerBootstrapTransaction:
    """Crash-durable outer bootstrap: release pin + exact persistent controller.

    This layer intentionally does not know Runtime Manager internals, services,
    models, participants, or scientific state.  It owns only the durable outer
    bootstrap transaction.  A possible external controller effect is never
    blindly replayed: a surviving ``CONTROLLER_EFFECT_PENDING`` state is first
    materialized as ``RECONCILE_REQUIRED`` and then routed through the session
    runtime, whose ``ensure`` contract is inspect-before-create.
    """

    def __init__(
        self,
        states: ServerBootstrapStatePort,
        pins: ReleasePinStorePort,
        sessions: PersistentSessionRuntimePort,
    ) -> None:
        self.states = states
        self.pins = pins
        self.sessions = sessions

    def _advance(
        self,
        state: ServerBootstrapState,
        phase: ServerBootstrapPhase,
        *,
        evidence_refs: tuple[str, ...] = (),
        error: BaseException | None = None,
    ) -> ServerBootstrapState:
        descriptor = None if error is None else describe_exception(error)
        updated = replace(
            state,
            phase=phase,
            revision=state.revision + 1,
            evidence_refs=state.evidence_refs + tuple(evidence_refs),
            last_error_type=None if descriptor is None else descriptor.error_type,
            last_error_digest=None if descriptor is None else descriptor.error_digest,
            updated_at=time.time(),
        )
        return self.states.write(updated, expected_revision=state.revision)

    def reconcile(
        self,
        *,
        control_id: str,
        runtime_manifest_digest: str,
        release_digest: str,
        session_policy_digest: str,
        spec: PersistentSessionSpec,
    ) -> ServerBootstrapTransactionReport:
        if spec.control_id != control_id or spec.runtime_manifest_digest != runtime_manifest_digest:
            raise ValueError("server bootstrap session spec identity mismatch")

        initial = ServerBootstrapState.create(
            control_id=control_id,
            runtime_manifest_digest=runtime_manifest_digest,
            release_digest=release_digest,
            session_spec_digest=spec.digest(),
            session_policy_digest=session_policy_digest,
        )

        # Bootstrap and release retirement share this lifecycle fence.  The
        # release is pinned before any controller effect and remains pinned for
        # BLOCKED/UNCERTAIN states until a separate retirement authority proves
        # quiescence.
        with self.pins.lifecycle(control_id, runtime_manifest_digest):
            state = self.states.load_or_create(initial)
            self.pins.acquire(control_id, runtime_manifest_digest, release_digest)

            if state.phase is ServerBootstrapPhase.BLOCKED:
                raise ServerBootstrapBlocked(
                    "server bootstrap is fail-closed after a prior identity/control failure; "
                    "diagnose the recorded evidence before starting a new frozen identity"
                )

            if state.phase is ServerBootstrapPhase.PLANNED:
                state = self._advance(
                    state,
                    ServerBootstrapPhase.RELEASE_PINNED,
                    evidence_refs=(f"release-pin:{release_digest}",),
                )

            if state.phase is ServerBootstrapPhase.CONTROLLER_EFFECT_PENDING:
                # A previous process disappeared while an external effect might
                # have been in flight.  Persist that fact before reconciliation.
                state = self._advance(
                    state,
                    ServerBootstrapPhase.RECONCILE_REQUIRED,
                    evidence_refs=("bootstrap-resume:controller-effect-uncertain",),
                )

            # Every actual session-runtime call gets a durable effect-window
            # marker first.  PersistentSessionRuntimePort.ensure() is required to
            # inspect the bound session before creating one, so resuming from
            # RECONCILE_REQUIRED cannot blindly duplicate the controller.
            state = self._advance(state, ServerBootstrapPhase.CONTROLLER_EFFECT_PENDING)
            try:
                report = self.sessions.ensure(spec)
            except PersistentSessionEffectUncertain as exc:
                self._advance(state, ServerBootstrapPhase.RECONCILE_REQUIRED, error=exc)
                raise
            except PersistentSessionDrift as exc:
                self._advance(state, ServerBootstrapPhase.BLOCKED, error=exc)
                raise
            except Exception as exc:
                # Unknown failures are never auto-classified as retryable.  They
                # are persisted as a blocked outer-bootstrap state with only a
                # stable sanitized error identity.
                self._advance(state, ServerBootstrapPhase.BLOCKED, error=exc)
                raise

            state = self._advance(
                state,
                ServerBootstrapPhase.COMMITTED,
                evidence_refs=(f"session-spec:{report.spec_digest}",) + tuple(report.evidence_refs),
            )
            return ServerBootstrapTransactionReport(state, report)


__all__ = ["ServerBootstrapTransaction"]
