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
    EffectIntent,
    EffectIntentConflict,
    EffectJournalIntegrityError,
)
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    InMemoryEffectIntentJournal,
    SQLiteEffectIntentJournal,
)


def _intent(
    *,
    run_id: str = "run-a",
    lifetime_id: str | None = "life",
    request_digest: str = "a" * 64,
    source_generation: str | None = None,
) -> EffectIntent:
    return EffectIntent.build(
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


def _effect(intent: EffectIntent, certainty: EffectCertainty, *, verification: bool = False) -> EffectReceipt:
    return EffectReceipt(
        "effect-a",
        intent.request_digest,
        EffectClass.RECONCILABLE,
        certainty,
        "provider-a",
        verification,
    )


def test_not_applied_rejects_verification_pending_no_effect_proof() -> None:
    intent = _intent()
    journals = [InMemoryEffectIntentJournal()]
    with TemporaryDirectory() as directory:
        journals.append(SQLiteEffectIntentJournal(Path(directory) / "effect.sqlite"))
        for journal in journals:
            journal.prepare(intent)
            with pytest.raises(EffectIntentConflict, match="authoritative bound NO_EFFECT"):
                journal.record_not_applied(
                    intent.intent_id,
                    request_digest=intent.request_digest,
                    effect=_effect(intent, EffectCertainty.NO_EFFECT, verification=True),
                )


def test_sqlite_effect_journal_detects_request_index_corruption() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = SQLiteEffectIntentJournal(path)
        intent = _intent()
        journal.prepare(intent)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET request_digest=? WHERE intent_id=?",
                ("b" * 64, intent.intent_id),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="request_digest index mismatch"):
            journal.load(intent.intent_id)


def test_sqlite_effect_journal_detects_effect_checksum_corruption() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = SQLiteEffectIntentJournal(path)
        intent = _intent()
        journal.prepare(intent)
        journal.record_result(
            intent.intent_id,
            request_digest=intent.request_digest,
            effect=_effect(intent, EffectCertainty.EFFECT_CONFIRMED),
        )
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET effect_digest=? WHERE intent_id=?",
                ("0" * 64, intent.intent_id),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="effect checksum mismatch"):
            journal.load(intent.intent_id)


def test_sqlite_effect_journal_detects_impossible_terminal_phase() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = SQLiteEffectIntentJournal(path)
        intent = _intent()
        journal.prepare(intent)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET phase='consumed' WHERE intent_id=?",
                (intent.intent_id,),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="CONSUMED"):
            journal.load(intent.intent_id)


def test_scope_query_rejects_index_row_injected_into_wrong_scope() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        journal = SQLiteEffectIntentJournal(path)
        intent = _intent(run_id="run-a", lifetime_id="life-a")
        journal.prepare(intent)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET lifetime_id='life-b' WHERE intent_id=?",
                (intent.intent_id,),
            )
            conn.commit()
        with pytest.raises(EffectJournalIntegrityError, match="lifetime_id index mismatch"):
            journal.unresolved_for_scope(run_id="run-a", lifetime_id="life-b")


def test_sqlite_effect_journal_timeout_must_be_finite() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        for timeout in (float("nan"), float("inf"), 0.0, -1.0):
            with pytest.raises(ValueError, match="finite and positive"):
                SQLiteEffectIntentJournal(path, timeout_seconds=timeout)


def test_effect_intent_prepare_fences_source_generation_replacement() -> None:
    original = _intent(request_digest="a" * 64, source_generation="env-g1")
    successor = _intent(request_digest="b" * 64, source_generation="env-g2")
    assert original.intent_id == successor.intent_id

    for journal in (InMemoryEffectIntentJournal(),):
        journal.prepare(original)
        with pytest.raises(EffectIntentConflict, match="identity conflict"):
            journal.prepare(successor)


def test_effect_transition_rejects_successor_request_digest_on_stale_intent() -> None:
    original = _intent(request_digest="a" * 64, source_generation="env-g1")
    successor = _intent(request_digest="b" * 64, source_generation="env-g2")
    journal = InMemoryEffectIntentJournal()
    journal.prepare(original)

    with pytest.raises(EffectIntentConflict, match="request digest conflict"):
        journal.record_result(
            original.intent_id,
            request_digest=successor.request_digest,
            effect=None,
        )


def test_sqlite_effect_generation_fence_survives_restart() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "effect.sqlite"
        original = _intent(request_digest="a" * 64, source_generation="env-g1")
        successor = _intent(request_digest="b" * 64, source_generation="env-g2")
        assert original.intent_id == successor.intent_id

        SQLiteEffectIntentJournal(path).prepare(original)
        reopened = SQLiteEffectIntentJournal(path)
        persisted = reopened.load(original.intent_id)
        assert persisted is not None
        assert persisted.intent.source_generation == "env-g1"
        assert persisted.intent.request_digest == original.request_digest

        with pytest.raises(EffectIntentConflict, match="identity conflict"):
            reopened.prepare(successor)
        with pytest.raises(EffectIntentConflict, match="request digest conflict"):
            reopened.record_result(
                original.intent_id,
                request_digest=successor.request_digest,
                effect=None,
            )
