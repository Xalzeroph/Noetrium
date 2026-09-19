from __future__ import annotations

from tests_support import environment_effect_intent

from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from pathlib import Path
import tempfile

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent

from noetrium_platform.infrastructure.reliability.effect.runtime import SQLiteEffectIntentJournal
from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, action_request_digest
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, ExecutionContext, canonical_bytes


def test_sqlite_journal_round_trips_opaque_recovery_handle_without_platform_interpretation():
    with tempfile.TemporaryDirectory() as td:
        context = ExecutionContext(
            "run", "trace", "span", study_id="study", lifetime_id="life",
            task_id="task", decision_cycle_id="dc", checkpoint_id="cp-1",
            participant_generations=(("environment", "world-7"),),
        )
        request = ActionRequest("action_dc", "provider-private", {"opaque": "caller-view"}, context)
        handle = PreparedEffectHandle.build(
            request_id=request.action_id,
            request_digest=action_request_digest(request),
            provider_schema="fake-provider.txn.v3",
            opaque_payload=b"\x00provider-private\xffrecovery-token",
            provider_instance_id="env-instance-9",
        )
        intent = environment_effect_intent(
            request, ComponentIdentity("environment.e", "e", "1", "1", "impl:1"),
            operation_id="dc:environment.act", recovery_handle=handle,
        )
        path = Path(td) / "actions.sqlite3"
        SQLiteEffectIntentJournal(path).prepare(intent)
        reopened = SQLiteEffectIntentJournal(path).load(intent.intent_id)
        assert reopened is not None
        assert reopened.intent.recovery_handle == handle
        assert reopened.intent.source_generation == "world-7"
        assert reopened.intent.checkpoint_id == "cp-1"


def test_recovery_handle_opaque_material_is_redacted_from_repr_and_canonical_operation_encoding():
    secret = b"provider-secret-recovery-material"
    handle = PreparedEffectHandle.build(
        request_id="action_dc", request_digest="r" * 64,
        provider_schema="fake-provider.txn.v3", opaque_payload=secret,
        provider_instance_id="env-instance-9",
    )
    assert secret.decode() not in repr(handle)
    encoded = canonical_bytes({"handle": handle})
    assert secret not in encoded
    assert handle.payload_sha256.encode() in encoded
