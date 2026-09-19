from __future__ import annotations

from tests_support import environment_effect_intent

from pathlib import Path
import tempfile

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectCompletionEvidence,
    EffectIntent,
    EffectIntentConflict,
    EffectIntentPhase,
)
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    InMemoryEffectIntentJournal,
    SQLiteEffectIntentJournal,
)
from noetrium_platform.capabilities.environment.runtime.api import ActionRequest
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, EffectClass, EffectReceipt, ExecutionContext


def _intent() -> EffectIntent:
    request = ActionRequest(
        "action_dc", "move", {"x": 1},
        ExecutionContext("run", "trace", "span", study_id="study", lifetime_id="life", task_id="task", decision_cycle_id="dc"),
    )
    return environment_effect_intent(
        request, ComponentIdentity("environment.e", "e", "1", "1", "impl:1"),
        operation_id="dc:environment.act",
    )


def _effect(intent: EffectIntent, certainty: EffectCertainty, *, verification: bool = False, suffix: str = "") -> EffectReceipt:
    return EffectReceipt(
        f"fx{suffix}", intent.request_digest, EffectClass.RECONCILABLE, certainty, "env", verification,
    )


def _consumption() -> EffectCompletionEvidence:
    return EffectCompletionEvidence("completion:run:dc", "dc:method.task_completed", "method-digest", "mg2")


def _journals():
    yield InMemoryEffectIntentJournal()
    with tempfile.TemporaryDirectory() as td:
        yield SQLiteEffectIntentJournal(Path(td) / "actions.sqlite3")


@pytest.mark.parametrize("certainty", [EffectCertainty.EFFECT_UNKNOWN, EffectCertainty.EFFECT_POSSIBLE, EffectCertainty.NO_EFFECT])
def test_consumed_requires_authoritatively_resolved_external_effect(certainty: EffectCertainty):
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(intent.intent_id, request_digest=intent.request_digest, effect=_effect(intent, certainty))
        with pytest.raises(EffectIntentConflict, match="CONSUMED terminal requires resolved"):
            journal.record_consumed(intent.intent_id, request_digest=intent.request_digest, consumption=_consumption())


def test_consumed_rejects_effect_that_still_requires_verification():
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(
            intent.intent_id,
            request_digest=intent.request_digest,
            effect=_effect(intent, EffectCertainty.EFFECT_CONFIRMED, verification=True),
        )
        with pytest.raises(EffectIntentConflict, match="CONSUMED terminal requires resolved"):
            journal.record_consumed(intent.intent_id, request_digest=intent.request_digest, consumption=_consumption())


@pytest.mark.parametrize("certainty", [EffectCertainty.EFFECT_CONFIRMED, EffectCertainty.EFFECT_REJECTED])
def test_consumed_accepts_final_applied_or_rejected_outcome(certainty: EffectCertainty):
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(intent.intent_id, request_digest=intent.request_digest, effect=_effect(intent, certainty))
        row = journal.record_consumed(intent.intent_id, request_digest=intent.request_digest, consumption=_consumption())
        assert row.phase is EffectIntentPhase.CONSUMED


def test_resolved_effect_cannot_later_flip_to_not_applied():
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        confirmed = _effect(intent, EffectCertainty.EFFECT_CONFIRMED)
        journal.record_reconciled(intent.intent_id, request_digest=intent.request_digest, effect=confirmed)
        with pytest.raises(EffectIntentConflict, match="resolved external effect cannot become NOT_APPLIED"):
            journal.record_not_applied(
                intent.intent_id,
                request_digest=intent.request_digest,
                effect=_effect(intent, EffectCertainty.NO_EFFECT, suffix=":none"),
            )


def test_uncertain_effect_may_resolve_to_not_applied():
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(
            intent.intent_id,
            request_digest=intent.request_digest,
            effect=_effect(intent, EffectCertainty.EFFECT_UNKNOWN),
        )
        row = journal.record_not_applied(
            intent.intent_id,
            request_digest=intent.request_digest,
            effect=_effect(intent, EffectCertainty.NO_EFFECT, suffix=":none"),
        )
        assert row.phase is EffectIntentPhase.NOT_APPLIED
