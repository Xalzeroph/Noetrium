from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
)
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntentConflict,
    EffectJournalIntegrityError,
    build_effect_intent,
    effect_completion,
    intent_field,
    record_field,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.truth import TruthModality, truth_modality
from noetrium_platform.foundation.kernel.event import causal_topological_order
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    memory_effect_intent_journal,
    sqlite_effect_intent_journal,
)


def _intent(
    *,
    run_id: str = "run-a",
    lifetime_id: str | None = "life",
    request_digest: str = "a" * 64,
    source_generation: str | None = None,
) -> NoetriumUnit:
    return build_effect_intent(
        request_id="request-a",
        request_digest=request_digest,
        operation_id="operation-a",
        provider_component=ComponentIdentity("provider.test", "test", "1", "1", "cfg"),
        context=ExecutionContext(
            run_id,
            "trace-a",
            "span-a",
            lifetime_id=lifetime_id,
            task_id="task-a",
        ),
        source_generation=source_generation,
        intent_namespace="integrity-test",
    )


def _effect(intent: NoetriumUnit, certainty: EffectCertainty) -> EffectReceipt:
    return EffectReceipt(
        effect_id="effect-a",
        request_digest=str(intent_field(intent, "request_digest")),
        effect_class=EffectClass.RECONCILABLE,
        certainty=certainty,
        provider_instance_id="provider-a",
    )


def test_not_applied_accepts_provider_no_effect_without_platform_reverification() -> None:
    intent = _intent()
    journals = [memory_effect_intent_journal()]
    with TemporaryDirectory() as directory:
        journals.append(sqlite_effect_intent_journal(Path(directory) / "effect.sqlite"))
        for journal in journals:
            journal.prepare(intent)
            row = journal.record_not_applied(
                str(intent_field(intent, "intent_id")),
                request_digest=str(intent_field(intent, "request_digest")),
                effect=_effect(intent, EffectCertainty.NO_EFFECT),
            )
            assert record_field(row, "phase").value == "not_applied"


def test_sqlite_effect_journal_detects_request_index_corruption() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = sqlite_effect_intent_journal(path)
        intent = _intent()
        journal.prepare(intent)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET request_digest=? WHERE intent_id=?",
                ("b" * 64, str(intent_field(intent, "intent_id"))),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="request_digest index mismatch"):
            journal.load(str(intent_field(intent, "intent_id")))


def test_sqlite_effect_journal_detects_effect_checksum_corruption() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = sqlite_effect_intent_journal(path)
        intent = _intent()
        journal.prepare(intent)
        journal.record_result(
            str(intent_field(intent, "intent_id")),
            request_digest=str(intent_field(intent, "request_digest")),
            effect=_effect(intent, EffectCertainty.EFFECT_CONFIRMED),
        )
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET effect_digest=? WHERE intent_id=?",
                ("0" * 64, str(intent_field(intent, "intent_id"))),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="effect checksum mismatch"):
            journal.load(str(intent_field(intent, "intent_id")))


def test_sqlite_effect_journal_detects_impossible_terminal_phase() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = sqlite_effect_intent_journal(path)
        intent = _intent()
        journal.prepare(intent)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET phase='consumed' WHERE intent_id=?",
                (str(intent_field(intent, "intent_id")),),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="CONSUMED"):
            journal.load(str(intent_field(intent, "intent_id")))


def test_scope_query_rejects_index_row_injected_into_wrong_scope() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = sqlite_effect_intent_journal(path)
        intent = _intent(run_id="run-a", lifetime_id="life-a")
        journal.prepare(intent)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET lifetime_id='life-b' WHERE intent_id=?",
                (str(intent_field(intent, "intent_id")),),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="lifetime_id index mismatch"):
            journal.unresolved_for_scope(run_id="run-a", lifetime_id="life-b")


def test_sqlite_effect_journal_timeout_must_be_finite() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        for timeout in (float("nan"), float("inf"), 0.0, -1.0):
            with pytest.raises(ValueError, match="finite and positive"):
                sqlite_effect_intent_journal(path, timeout_seconds=timeout)


def test_effect_intent_prepare_fences_source_generation_replacement() -> None:
    original = _intent(request_digest="a" * 64, source_generation="env-g1")
    successor = _intent(request_digest="b" * 64, source_generation="env-g2")
    assert str(intent_field(original, "intent_id")) == str(intent_field(successor, "intent_id"))

    for journal in (memory_effect_intent_journal(),):
        journal.prepare(original)
        with pytest.raises(EffectIntentConflict, match="identity conflict"):
            journal.prepare(successor)


def test_effect_transition_rejects_successor_request_digest_on_stale_intent() -> None:
    original = _intent(request_digest="a" * 64, source_generation="env-g1")
    successor = _intent(request_digest="b" * 64, source_generation="env-g2")
    journal = memory_effect_intent_journal()
    journal.prepare(original)

    with pytest.raises(EffectIntentConflict, match="request digest conflict"):
        journal.record_result(
            str(intent_field(original, "intent_id")),
            request_digest=str(intent_field(successor, "request_digest")),
            effect=None,
        )


def test_sqlite_effect_generation_fence_survives_restart() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        original = _intent(request_digest="a" * 64, source_generation="env-g1")
        successor = _intent(request_digest="b" * 64, source_generation="env-g2")
        assert str(intent_field(original, "intent_id")) == str(intent_field(successor, "intent_id"))

        sqlite_effect_intent_journal(path).prepare(original)
        reopened = sqlite_effect_intent_journal(path)
        persisted = reopened.load(str(intent_field(original, "intent_id")))
        assert persisted is not None
        assert intent_field(record_field(persisted, "intent"), "source_generation") == "env-g1"
        assert intent_field(record_field(persisted, "intent"), "request_digest") == intent_field(original, "request_digest")

        with pytest.raises(EffectIntentConflict, match="identity conflict"):
            reopened.prepare(successor)
        with pytest.raises(EffectIntentConflict, match="request digest conflict"):
            reopened.record_result(
                str(intent_field(original, "intent_id")),
                request_digest=str(intent_field(successor, "request_digest")),
                effect=None,
            )


def test_sqlite_effect_projection_rebuilds_from_causal_events_across_restart() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        intent = _intent(run_id="run-replay", lifetime_id="life-replay")
        intent_id = str(intent_field(intent, "intent_id"))
        request_digest = str(intent_field(intent, "request_digest"))

        journal = sqlite_effect_intent_journal(path)
        prepared = journal.prepare(intent).record
        assert record_field(prepared, "phase").value == "prepared"
        assert journal.verify_projection_rebuild("run-replay") == (prepared,)
        events = journal.events_for_run("run-replay")
        assert len(events) == 1
        assert truth_modality(events[0]) is TruthModality.AUTHORIZED
        journal.close()

        journal = sqlite_effect_intent_journal(path)
        result = journal.record_result(
            intent_id,
            request_digest=request_digest,
            effect=_effect(intent, EffectCertainty.EFFECT_CONFIRMED),
        )
        assert record_field(result, "phase").value == "result_recorded"
        assert journal.verify_projection_rebuild("run-replay") == (result,)
        events = journal.events_for_run("run-replay")
        assert len(events) == 2
        assert truth_modality(causal_topological_order(events)[-1]) is TruthModality.OBSERVED
        journal.close()

        journal = sqlite_effect_intent_journal(path)
        reconciled = journal.record_reconciled(
            intent_id,
            request_digest=request_digest,
            effect=_effect(intent, EffectCertainty.EFFECT_CONFIRMED),
        )
        assert record_field(reconciled, "phase").value == "reconciled"
        assert journal.verify_projection_rebuild("run-replay") == (reconciled,)
        events = journal.events_for_run("run-replay")
        assert len(events) == 3
        assert truth_modality(causal_topological_order(events)[-1]) is TruthModality.OBSERVED
        journal.close()

        journal = sqlite_effect_intent_journal(path)
        completion = effect_completion(
            completion_key="completion-a",
            completion_operation_id="consumer-op",
            consumer_component_digest="c" * 64,
            consumer_generation="consumer-g1",
        )
        consumed = journal.record_consumed(
            intent_id,
            request_digest=request_digest,
            consumption=completion,
        )
        assert record_field(consumed, "phase").value == "consumed"
        assert record_field(consumed, "consumption") == completion
        assert journal.verify_projection_rebuild("run-replay") == (consumed,)
        events = journal.events_for_run("run-replay")
        assert len(events) == 4
        assert truth_modality(causal_topological_order(events)[-1]) is TruthModality.AUTHORIZED
        journal.close()
