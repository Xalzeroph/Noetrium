from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile

from noetrium_platform.infrastructure.reliability.effect.api import EffectCompletionEvidence, EffectIntent
from noetrium_platform.infrastructure.reliability.effect.runtime import InMemoryEffectIntentJournal, SQLiteEffectIntentJournal
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, EffectClass, EffectReceipt, ExecutionContext


def _intent(*, request_id: str, run_id: str, lifetime_id: str | None) -> EffectIntent:
    context = ExecutionContext(
        run_id,
        f"trace:{request_id}",
        f"span:{request_id}",
        lifetime_id=lifetime_id,
    )
    return EffectIntent.build(
        request_id=request_id,
        request_digest=(request_id.encode().hex() + "0" * 64)[:64],
        operation_id=f"op:{request_id}",
        provider_component=ComponentIdentity("provider.test", "test", "1", "1", "cfg"),
        context=context,
        recovery_handle=None,
        intent_namespace="scope-index-test",
    )


def test_sqlite_scope_query_filters_before_document_decode() -> None:
    """An unrelated corrupted row must not be materialized for another run's recovery query."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "effects.sqlite3"
        journal = SQLiteEffectIntentJournal(path)
        keep = _intent(request_id="keep", run_id="run-a", lifetime_id="life")
        poison = _intent(request_id="poison", run_id="run-b", lifetime_id="life")
        journal.prepare(keep)
        journal.prepare(poison)

        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET intent_json='not-json' WHERE intent_id=?",
                (poison.intent_id,),
            )
            conn.commit()
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(effect_intents)")}
        assert "effect_intents_scope_phase_idx" in indexes

        rows = journal.unresolved_for_scope(run_id="run-a", lifetime_id="life")
        assert tuple(row.intent.intent_id for row in rows) == (keep.intent_id,)


def test_memory_scope_index_removes_terminal_intents_without_global_scan() -> None:
    journal = InMemoryEffectIntentJournal()
    a = _intent(request_id="a", run_id="run-a", lifetime_id="life")
    b = _intent(request_id="b", run_id="run-b", lifetime_id="life")
    journal.prepare(a)
    journal.prepare(b)

    assert tuple(row.intent.intent_id for row in journal.unresolved_for_scope(
        run_id="run-a", lifetime_id="life"
    )) == (a.intent_id,)

    journal.record_result(
        a.intent_id,
        request_digest=a.request_digest,
        effect=EffectReceipt(
            "fx:a", a.request_digest, EffectClass.RECONCILABLE,
            EffectCertainty.EFFECT_CONFIRMED, "provider", False,
        ),
    )
    journal.record_consumed(
        a.intent_id,
        request_digest=a.request_digest,
        consumption=EffectCompletionEvidence("done", "op:done", "consumer", None),
    )
    assert journal.unresolved_for_scope(run_id="run-a", lifetime_id="life") == ()
    assert tuple(row.intent.intent_id for row in journal.unresolved_for_scope(
        run_id="run-b", lifetime_id="life"
    )) == (b.intent_id,)
