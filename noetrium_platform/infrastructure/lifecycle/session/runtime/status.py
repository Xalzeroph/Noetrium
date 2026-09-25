from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionBindingStorePort,
    PersistentSessionControlPort,
    PersistentSessionDrift,
    PersistentSessionReasonCode,
    PersistentSessionObservation,
    PersistentSessionObservationState,
    PersistentSessionSpec,
)



class BoundPersistentSessionStatusProbe:
    """Read-only persistent-session observer; never creates or terminates sessions."""

    def __init__(
        self,
        control: PersistentSessionControlPort,
        bindings: PersistentSessionBindingStorePort,
        session_name: str,
        expected_spec: PersistentSessionSpec | None = None,
    ) -> None:
        self.control = control
        self.bindings = bindings
        self.session_name = session_name
        self.expected_spec = expected_spec

    def observe(self) -> PersistentSessionObservation:
        binding = self.bindings.read(self.session_name)
        if binding is None:
            return PersistentSessionObservation(
                self.session_name,
                PersistentSessionObservationState.UNBOUND,
                "persistent server-session binding missing",
                reason_code=PersistentSessionReasonCode.BINDING_MISSING.value,
            )
        if self.expected_spec is not None and binding.spec != self.expected_spec:
            return PersistentSessionObservation(
                self.session_name,
                PersistentSessionObservationState.DRIFT,
                "persistent-session binding differs from the current server profile",
                evidence_refs=(
                    f"session-binding:{binding.spec_digest}",
                    f"expected-session-binding:{self.expected_spec.digest()}",
                ),
                reason_code=PersistentSessionReasonCode.BINDING_DRIFT.value,
            )
        if binding.control_identity_digest != self.control.identity_digest:
            return PersistentSessionObservation(
                self.session_name,
                PersistentSessionObservationState.DRIFT,
                "persistent-session transport identity differs from durable binding",
                evidence_refs=(f"session-binding:{binding.spec_digest}",),
                reason_code=PersistentSessionReasonCode.TRANSPORT_IDENTITY_DRIFT.value,
            )
        try:
            snapshot = self.control.inspect(self.session_name)
        except Exception as exc:
            descriptor = describe_exception(exc)
            return PersistentSessionObservation(
                self.session_name,
                PersistentSessionObservationState.UNAVAILABLE,
                f"persistent-session control unavailable: {descriptor.error_type}: "
                f"{descriptor.safe_message}; error_digest={descriptor.error_digest}",
                evidence_refs=(f"session-binding:{binding.spec_digest}",),
                reason_code=PersistentSessionReasonCode.CONTROL_UNAVAILABLE.value,
            )
        refs = (f"session-binding:{binding.spec_digest}",) + tuple(snapshot.evidence_refs)
        if not snapshot.exists:
            return PersistentSessionObservation(
                self.session_name,
                PersistentSessionObservationState.MISSING,
                "persistent controller session missing; service/runtime authorities must be checked separately",
                evidence_refs=refs,
                attach_argv=self.control.attach_argv(self.session_name),
                reason_code=PersistentSessionReasonCode.SESSION_MISSING.value,
            )
        try:
            exact_refs = self.control.verify_snapshot(binding.spec, snapshot)
        except PersistentSessionDrift as exc:
            descriptor = describe_exception(exc)
            return PersistentSessionObservation(
                self.session_name,
                PersistentSessionObservationState.DRIFT,
                descriptor.safe_message,
                controller_pid=snapshot.controller_pid,
                evidence_refs=refs,
                attach_argv=self.control.attach_argv(self.session_name),
                reason_code=exc.code.value,
            )
        except Exception as exc:
            descriptor = describe_exception(exc)
            return PersistentSessionObservation(
                self.session_name,
                PersistentSessionObservationState.UNAVAILABLE,
                f"persistent-session verification unavailable: {descriptor.error_type}: "
                f"{descriptor.safe_message}; error_digest={descriptor.error_digest}",
                controller_pid=snapshot.controller_pid,
                evidence_refs=refs,
                reason_code=PersistentSessionReasonCode.VERIFICATION_UNAVAILABLE.value,
            )
        return PersistentSessionObservation(
            self.session_name,
            PersistentSessionObservationState.EXACT,
            f"exact {self.control.backend_id} controller pid={snapshot.controller_pid}",
            controller_pid=snapshot.controller_pid,
            evidence_refs=refs + tuple(exact_refs),
            attach_argv=self.control.attach_argv(self.session_name),
            reason_code=PersistentSessionReasonCode.EXACT.value,
        )


__all__ = ["BoundPersistentSessionStatusProbe"]
