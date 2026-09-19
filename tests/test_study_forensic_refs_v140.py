from __future__ import annotations

from tests_support import environment_effect_intent

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from pathlib import Path
import tempfile

from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent
from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, action_request_digest
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, ExecutionContext, OperationExecutor, OperationRequest
from noetrium_platform.research.execution.workflow.implementations.context_action.forensic_refs import StudyOperationFailureReferenceProjector


def test_action_failure_projects_only_safe_digest_correlations_not_opaque_handle_material():
    secret = b"provider-private-secret-material"
    context = ExecutionContext(
        "run", "trace", "span", study_id="study", task_id="task", decision_cycle_id="dc",
        checkpoint_id="cp-1", participant_generations=(("environment", "world-1"),),
    )
    action = ActionRequest("action_dc", "move", {"n": 1}, context)
    handle = PreparedEffectHandle.build(
        request_id=action.action_id, request_digest=action_request_digest(action),
        provider_schema="provider.tx.v7", opaque_payload=secret,
    )
    intent = environment_effect_intent(
        action, ComponentIdentity("environment.e", "e", "1", "1", "g"),
        operation_id="dc:environment.act", recovery_handle=handle,
    )
    identity = ComponentIdentity("platform.action_intent_journal", "j", "1", "1", "g")
    request = OperationRequest(
        "op", "invocation:test-forensic-refs", "environment.action_intent.prepare", context, identity, identity,
        intent, "v1", "digest", idempotency_key=intent.intent_id,
    )
    with tempfile.TemporaryDirectory() as td, ForensicStore(Path(td)) as store:
        sink = OperationForensicFailureSink(
            store, reference_projector=StudyOperationFailureReferenceProjector()
        )
        result = OperationExecutor(sink).execute(request, lambda _: (_ for _ in ()).throw(OSError("disk failed")))
        assert result.failure_id
        failure = store.failures.verified_payloads_after(0).payloads[0]
        serialized = str(failure)
        assert secret.decode() not in serialized
        assert f"action-intent:{intent.intent_id}" in failure["correlation_refs"]
        assert "provider-recovery-schema:provider.tx.v7" in failure["correlation_refs"]
        assert f"provider-recovery-payload:{handle.payload_sha256}" in failure["correlation_refs"]
        assert f"action-request:{intent.request_digest}" in failure["request_refs"]
