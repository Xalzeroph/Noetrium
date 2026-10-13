from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.runtime import sqlite_effect_intent_journal


from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_effect_journal import (
    ServiceStartEffectJournal,
)


def _contract() -> ServiceLaunchContract:
    return ServiceLaunchContract(
        service_id="service.effect",
        generation="generation-1",
        executable="/bin/true",
        argv=("/bin/true",),
        cwd="/tmp",
        environment_digest="a" * 64,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
        readiness_timeout_s=5.0,
        stop_timeout_s=5.0,
        heartbeat_interval_s=1.0,
    )


def test_service_start_is_one_effect_causal_journal(tmp_path):
    contract = _contract()
    journal = ServiceStartEffectJournal(sqlite_effect_intent_journal(tmp_path / "effects.sqlite3"))
    intent = journal.prepare(contract, attempt=1, recovery_handle=None)
    intent = journal.record_process(
        intent,
        ServiceProcessIdentity(123, "start:123"),
    )
    intent = journal.state_committed(intent)
    intent = journal.complete(intent)

    assert intent.phase.value == "complete"
    assert journal.unresolved(contract) is None
    rebuilt = journal.journal.verify_projection_rebuild("service:" + contract.service_id)
    assert len(rebuilt) == 1


def test_abort_before_process_is_not_applied(tmp_path):
    contract = _contract()
    journal = ServiceStartEffectJournal(sqlite_effect_intent_journal(tmp_path / "effects.sqlite3"))
    intent = journal.prepare(contract, attempt=1, recovery_handle=None)
    intent = journal.abort(intent)

    assert intent.phase.value == "aborted"
    assert intent.process is None
    assert journal.unresolved(contract) is None
    journal.journal.verify_projection_rebuild("service:" + contract.service_id)


def test_abort_after_process_consumes_confirmed_effect(tmp_path):
    contract = _contract()
    journal = ServiceStartEffectJournal(sqlite_effect_intent_journal(tmp_path / "effects.sqlite3"))
    intent = journal.prepare(contract, attempt=1, recovery_handle=None)
    process = ServiceProcessIdentity(456, "start:456")
    intent = journal.record_process(intent, process)
    intent = journal.abort(intent)

    assert intent.phase.value == "aborted"
    assert intent.process == process
    assert journal.unresolved(contract) is None
    journal.journal.verify_projection_rebuild("service:" + contract.service_id)
