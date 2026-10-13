from __future__ import annotations

from tests_support import environment_effect_intent

from pathlib import Path
import tempfile

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntentConflict,
    EffectIntentPhase,
    effect_completion,
    intent_field,
    record_field,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    memory_effect_intent_journal,
    sqlite_effect_intent_journal,
)
from noetrium_platform.capabilities.environment.api import ActionRequest
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, EffectClass, EffectReceipt, ExecutionContext


def _intent() -> NoetriumUnit:
    request = ActionRequest(
        "action_dc", "move", {"x": 1},
        ExecutionContext("run", "trace", "span", study_id="study", lifetime_id="life", task_id="task", decision_cycle_id="dc"),
    )
    return environment_effect_intent(
        request, ComponentIdentity("environment.e", "e", "1", "1", "impl:1"),
        operation_id="dc:environment.act",
    )


def _effect(intent: NoetriumUnit, certainty: EffectCertainty, *, suffix: str = "") -> EffectReceipt:
    return EffectReceipt(
        effect_id=f"fx{suffix}",
        request_digest=str(intent_field(intent, "request_digest")),
        effect_class=EffectClass.RECONCILABLE,
        certainty=certainty,
        provider_instance_id="env",
    )


def _consumption() -> NoetriumUnit:
    return effect_completion(
        completion_key="completion:run:dc",
        completion_operation_id="dc:method.task_completed",
        consumer_component_digest="method-digest",
        consumer_generation="mg2",
    )


def _journals():
    yield memory_effect_intent_journal()
    with tempfile.TemporaryDirectory() as td:
        yield sqlite_effect_intent_journal(Path(td) / "actions.sqlite3")


@pytest.mark.parametrize("certainty", [EffectCertainty.INDETERMINATE, EffectCertainty.NO_EFFECT])
def test_consumed_requires_authoritatively_resolved_external_effect(certainty: EffectCertainty):
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(str(intent_field(intent, "intent_id")), request_digest=str(intent_field(intent, "request_digest")), effect=_effect(intent, certainty))
        with pytest.raises(EffectIntentConflict, match="CONSUMED terminal requires resolved"):
            journal.record_consumed(str(intent_field(intent, "intent_id")), request_digest=str(intent_field(intent, "request_digest")), consumption=_consumption())


def test_consumed_accepts_provider_confirmed_without_platform_reverification():
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(
            str(intent_field(intent, "intent_id")),
            request_digest=str(intent_field(intent, "request_digest")),
            effect=_effect(intent, EffectCertainty.EFFECT_CONFIRMED),
        )
        row = journal.record_consumed(
            str(intent_field(intent, "intent_id")),
            request_digest=str(intent_field(intent, "request_digest")),
            consumption=_consumption(),
        )
        assert record_field(row, "phase") is EffectIntentPhase.CONSUMED


@pytest.mark.parametrize("certainty", [EffectCertainty.EFFECT_CONFIRMED, EffectCertainty.EFFECT_REJECTED])
def test_consumed_accepts_final_applied_or_rejected_outcome(certainty: EffectCertainty):
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(str(intent_field(intent, "intent_id")), request_digest=str(intent_field(intent, "request_digest")), effect=_effect(intent, certainty))
        row = journal.record_consumed(str(intent_field(intent, "intent_id")), request_digest=str(intent_field(intent, "request_digest")), consumption=_consumption())
        assert record_field(row, "phase") is EffectIntentPhase.CONSUMED


def test_resolved_effect_cannot_later_flip_to_not_applied():
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        confirmed = _effect(intent, EffectCertainty.EFFECT_CONFIRMED)
        journal.record_reconciled(str(intent_field(intent, "intent_id")), request_digest=str(intent_field(intent, "request_digest")), effect=confirmed)
        with pytest.raises(EffectIntentConflict, match="resolved external effect cannot become NOT_APPLIED"):
            journal.record_not_applied(
                str(intent_field(intent, "intent_id")),
                request_digest=str(intent_field(intent, "request_digest")),
                effect=_effect(intent, EffectCertainty.NO_EFFECT, suffix=":none"),
            )


def test_uncertain_effect_may_resolve_to_not_applied():
    for journal in _journals():
        intent = _intent(); journal.prepare(intent)
        journal.record_result(
            str(intent_field(intent, "intent_id")),
            request_digest=str(intent_field(intent, "request_digest")),
            effect=_effect(intent, EffectCertainty.INDETERMINATE),
        )
        row = journal.record_not_applied(
            str(intent_field(intent, "intent_id")),
            request_digest=str(intent_field(intent, "request_digest")),
            effect=_effect(intent, EffectCertainty.NO_EFFECT, suffix=":none"),
        )
        assert record_field(row, "phase") is EffectIntentPhase.NOT_APPLIED
