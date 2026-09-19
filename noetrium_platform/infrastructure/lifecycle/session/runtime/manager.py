from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionBinding,
    PersistentSessionBindingStorePort,
    PersistentSessionControlPort,
    PersistentSessionDrift,
    PersistentSessionReasonCode,
    PersistentSessionReport,
    PersistentSessionSnapshot,
    PersistentSessionSpec,
)



class PersistentSessionManager:
    """Durable frozen binding + exact backend reconciliation.

    The manager owns no tmux/systemd-specific behavior.  It binds a frozen
    session specification to one verified transport identity and delegates all
    external effects through ``PersistentSessionControlPort``.
    """

    def __init__(
        self,
        control: PersistentSessionControlPort,
        bindings: PersistentSessionBindingStorePort,
    ) -> None:
        self.control = control
        self.bindings = bindings

    @property
    def backend_id(self) -> str:
        return self.control.backend_id

    @property
    def transport_identity_digest(self) -> str:
        return self.control.identity_digest

    @property
    def transport_identity_verified(self) -> bool:
        return self.control.identity_verified

    def _expected(self, spec: PersistentSessionSpec) -> PersistentSessionBinding:
        return PersistentSessionBinding.from_spec(spec, self.control.identity_digest)

    def ensure(self, spec: PersistentSessionSpec) -> PersistentSessionReport:
        expected = self._expected(spec)
        existing_binding = self.bindings.bind_once(expected)
        if existing_binding != expected:
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.BINDING_DRIFT,
                "persistent session name is already bound to a different frozen runtime command/transport",
            )

        snapshot = self.control.inspect(spec.session_name)
        reused = snapshot.exists
        if not snapshot.exists:
            snapshot = self.control.create_detached(spec)
        refs = self.control.verify_snapshot(spec, snapshot)
        return PersistentSessionReport(
            expected.spec_digest,
            snapshot,
            self.control.attach_argv(spec.session_name),
            reused,
            tuple(snapshot.evidence_refs) + tuple(refs),
        )

    def inspect(self, spec: PersistentSessionSpec) -> PersistentSessionSnapshot:
        binding = self.bindings.read(spec.session_name)
        if binding is None or binding != self._expected(spec):
            raise PersistentSessionDrift(PersistentSessionReasonCode.BINDING_DRIFT, "persistent session binding missing or drifted")
        snapshot = self.control.inspect(spec.session_name)
        self.control.verify_snapshot(spec, snapshot)
        return snapshot

    def terminate(self, spec: PersistentSessionSpec) -> tuple[str, ...]:
        binding = self.bindings.read(spec.session_name)
        if binding is None or binding != self._expected(spec):
            raise PersistentSessionDrift(PersistentSessionReasonCode.BINDING_DRIFT, "refusing to terminate an unbound/drifted persistent session")
        return self.control.terminate(spec.session_name)

    def attach(self, spec: PersistentSessionSpec) -> tuple[str, ...]:
        """Prepare an attach only after proving the frozen session is exact.

        Attaching is interactive, but it still crosses a server boundary.  A
        caller must not be able to turn the transport into a generic
        ``tmux attach`` primitive by asking the control adapter for an argv
        directly.  The durable binding and the live snapshot are therefore
        checked immediately before the TTY argv is materialized.
        """

        binding = self.bindings.read(spec.session_name)
        if binding is None or binding != self._expected(spec):
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.BINDING_DRIFT,
                "refusing to attach to an unbound/drifted persistent session",
            )
        snapshot = self.control.inspect(spec.session_name)
        self.control.verify_snapshot(spec, snapshot)
        return self.control.attach_argv(spec.session_name)


__all__ = ["PersistentSessionManager"]
