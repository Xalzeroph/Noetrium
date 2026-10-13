from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile

from noetrium_platform.infrastructure.reliability.effect.api import (
    build_effect_intent,
    effect_completion,
    intent_field,
    record_field,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.runtime import memory_effect_intent_journal, sqlite_effect_intent_journal
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, EffectClass, EffectReceipt, ExecutionContext


def _intent(*, request_id: str, run_id: str, lifetime_id: str | None) -> NoetriumUnit:
    context = ExecutionContext(
        run_id,
        f"trace:{request_id}",
        f"span:{request_id}",
        lifetime_id=lifetime_id,
    )
    return build_effect_intent(
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
        journal = sqlite_effect_intent_journal(path)
        keep = _intent(request_id="keep", run_id="run-a", lifetime_id="life")
        poison = _intent(request_id="poison", run_id="run-b", lifetime_id="life")
        journal.prepare(keep)
        journal.prepare(poison)

        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "UPDATE effect_intents SET intent_json='not-json' WHERE intent_id=?",
                (str(intent_field(poison, "intent_id")),),
            )
            conn.commit()
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(effect_intents)")}
        assert "effect_intents_scope_phase_idx" in indexes

        rows = journal.unresolved_for_scope(run_id="run-a", lifetime_id="life")
        assert tuple(intent_field(record_field(row, "intent"), "intent_id") for row in rows) == (str(intent_field(keep, "intent_id")),)


def test_memory_scope_index_removes_terminal_intents_without_global_scan() -> None:
    journal = memory_effect_intent_journal()
    a = _intent(request_id="a", run_id="run-a", lifetime_id="life")
    b = _intent(request_id="b", run_id="run-b", lifetime_id="life")
    journal.prepare(a)
    journal.prepare(b)

    assert tuple(intent_field(record_field(row, "intent"), "intent_id") for row in journal.unresolved_for_scope(
        run_id="run-a", lifetime_id="life"
    )) == (str(intent_field(a, "intent_id")),)

    journal.record_result(
        str(intent_field(a, "intent_id")),
        request_digest=str(intent_field(a, "request_digest")),
        effect=EffectReceipt(
            "fx:a", str(intent_field(a, "request_digest")), EffectClass.RECONCILABLE,
            EffectCertainty.EFFECT_CONFIRMED, provider_instance_id="provider",
        ),
    )
    journal.record_consumed(
        str(intent_field(a, "intent_id")),
        request_digest=str(intent_field(a, "request_digest")),
        consumption=effect_completion(
            completion_key="done",
            completion_operation_id="op:done",
            consumer_component_digest="consumer",
            consumer_generation=None,
        ),
    )
    assert journal.unresolved_for_scope(run_id="run-a", lifetime_id="life") == ()
    assert tuple(intent_field(record_field(row, "intent"), "intent_id") for row in journal.unresolved_for_scope(
        run_id="run-b", lifetime_id="life"
    )) == (str(intent_field(b, "intent_id")),)
