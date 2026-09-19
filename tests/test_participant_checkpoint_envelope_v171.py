from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity
from noetrium_platform.capabilities.participant.core.api.checkpoint import (
    ParticipantCheckpoint,
    ParticipantCheckpointIdentityMismatch,
)
from noetrium_platform.capabilities.participant.session.runtime.checkpoint_runtime import ParticipantCheckpointRuntime

CHECKPOINT_RUNTIME = ParticipantCheckpointRuntime()
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity,
    ParticipantRuntimeBinding,
)
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle
from tests_support import runtime_identity_for_test


class Session:
    def __init__(self) -> None:
        self.payload = b"state"


class Adapter:
    kind = "test"

    @staticmethod
    def _component(binding: ParticipantRuntimeBinding) -> ComponentIdentity:
        i = binding.implementation
        return ComponentIdentity(
            f"participant.{binding.role}", i.digest(), i.implementation_version,
            i.schema_version, binding.configuration_digest or "default",
        )

    def actual_component(self, participant: ParticipantRuntimeHandle) -> ComponentIdentity:
        return self._component(participant.binding)

    def checkpoint(self, participant, session, *, session_id):
        return ParticipantCheckpoint.capture(
            binding=participant.binding,
            component=self.actual_component(participant),
            session_id=session_id,
            opaque_payload=session.payload,
        )

    def restore(self, participant, session, checkpoint, *, session_id):
        session.payload = checkpoint.opaque_payload


def binding(*, role="method", config="cfg") -> ParticipantRuntimeBinding:
    return ParticipantRuntimeBinding(
        role,
        ParticipantImplementationIdentity("test", "impl", "1", "1", "1", "a" * 64),
        runtime_identity_for_test("test"),
        config,
    )


def test_checkpoint_binds_runtime_configuration_role_component_and_session():
    adapter = Adapter()
    original_binding = binding()
    participant = ParticipantRuntimeHandle(original_binding, object())
    session = Session()
    checkpoint = CHECKPOINT_RUNTIME.capture(adapter, participant, session, session_id="session-1")

    for mismatched in (
        ParticipantRuntimeHandle(binding(role="other"), object()),
        ParticipantRuntimeHandle(binding(config="other-config"), object()),
    ):
        with pytest.raises(ParticipantCheckpointIdentityMismatch):
            CHECKPOINT_RUNTIME.restore(adapter, mismatched, Session(), checkpoint, session_id="session-1")

    with pytest.raises(ParticipantCheckpointIdentityMismatch):
        CHECKPOINT_RUNTIME.restore(adapter, participant, Session(), checkpoint, session_id="session-2")


def test_checkpoint_payload_tamper_fails_before_domain_restore():
    adapter = Adapter()
    participant = ParticipantRuntimeHandle(binding(), object())
    checkpoint = CHECKPOINT_RUNTIME.capture(adapter, participant, Session(), session_id="session")
    tampered = replace(checkpoint, opaque_payload=b"tampered")
    target = Session()
    target.payload = b"untouched"

    with pytest.raises(ParticipantCheckpointIdentityMismatch):
        CHECKPOINT_RUNTIME.restore(adapter, participant, target, tampered, session_id="session")
    assert target.payload == b"untouched"


def test_capture_rejects_adapter_checkpoint_from_wrong_binding():
    class WrongAdapter(Adapter):
        def checkpoint(self, participant, session, *, session_id):
            wrong = ParticipantRuntimeHandle(binding(config="wrong"), object())
            return ParticipantCheckpoint.capture(
                binding=wrong.binding,
                component=self.actual_component(wrong),
                session_id=session_id,
                opaque_payload=session.payload,
            )

    participant = ParticipantRuntimeHandle(binding(), object())
    with pytest.raises(ParticipantCheckpointIdentityMismatch):
        CHECKPOINT_RUNTIME.capture(WrongAdapter(), participant, Session(), session_id="session")
