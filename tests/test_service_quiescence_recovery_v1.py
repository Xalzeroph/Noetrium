from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.runtime import sqlite_effect_intent_journal


from dataclasses import replace
from pathlib import Path

import pytest

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)
from noetrium_platform.infrastructure.lifecycle.service.composition import (
    build_service_supervisor,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceRuntimeEndpoint,
    ServicePhase,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.prepared_start import (
    PreparedServiceStartReconcileResult,
    PreparedServiceStartStatus,
    ServiceStartRecoveryHandle,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.service_quiescence_control import (
    ServiceQuiescenceRecoveryRequired,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.service_state_contracts import (
    ServiceSupervisorState,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_effect_journal import (
    ServiceStartEffectJournal,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import (
    FileServiceStateStore,
)


def _contract() -> ServiceLaunchContract:
    return ServiceLaunchContract(
        service_id="service.quiescence",
        generation="generation-1",
        executable="/bin/true",
        argv=("/bin/true",),
        cwd="/tmp",
        environment_digest="a" * 64,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
        readiness_timeout_s=30.0,
        stop_timeout_s=10.0,
        heartbeat_interval_s=5.0,
    )


class _Adapter:
    start_recovery_durability = "crash_durable"

    def __init__(
        self,
        *,
        live: ServiceProcessIdentity | None = None,
        prepared_status: PreparedServiceStartStatus = (
            PreparedServiceStartStatus.NOT_STARTED
        ),
    ) -> None:
        self.live = live
        self.prepared_status = prepared_status
        self.stopped: list[ServiceProcessIdentity] = []

    def reconcile(self, state, contract):
        if state.process is None:
            return None, ("process:none",)
        if self.live is None:
            return None, ("process:missing",)
        return self.live, ("process:exact",)

    def start(self, contract):
        raise AssertionError("not used")

    def wait_ready(self, process, contract):
        raise AssertionError("not used")

    def stop(self, process, contract):
        assert self.live == process
        self.stopped.append(process)
        self.live = None
        return ("process:stopped",)

    def prepare_start_recovery(self, contract, *, intent_id, attempt):
        return ServiceStartRecoveryHandle.from_payload(
            "test.prepared.v1",
            f"{intent_id}:{attempt}".encode(),
        )

    def start_prepared(self, contract, handle):
        raise AssertionError("not used")

    def reconcile_prepared_start(self, contract, handle):
        if self.prepared_status is PreparedServiceStartStatus.PROCESS_CONFIRMED:
            assert self.live is not None
            return PreparedServiceStartReconcileResult(
                self.prepared_status,
                self.live,
                ("prepared:exact",),
            )
        return PreparedServiceStartReconcileResult(
            self.prepared_status,
            None,
            ("prepared:observed",),
            (
                None
                if self.prepared_status is PreparedServiceStartStatus.NOT_STARTED
                else "prepared effect is uncertain"
            ),
        )


def _runtime(tmp_path: Path, adapter: _Adapter):
    contract = _contract()
    state_store = FileServiceStateStore(tmp_path / "state.json")
    start_effects = ServiceStartEffectJournal(sqlite_effect_intent_journal(
        tmp_path / "start-effects.sqlite3"
        )
    )
    initial = ServiceSupervisorState.initial(
        contract.service_id,
        contract.digest(),
    )
    state_store.write(
        replace(
            initial,
            phase=ServicePhase.START_CHILD,
            attempt=1,
            process=None,
        )
    )
    supervisor = build_service_supervisor(
        state_store,
        start_effects,
        adapter,
    )
    return (
        contract,
        state_store,
        start_effects,
        start_effects,
        ExactServiceRuntimeEndpoint(supervisor),
    )


def test_quiesce_recovers_process_confirmed_start_before_state_commit(
    tmp_path: Path,
) -> None:
    process = ServiceProcessIdentity(
        901,
        "docker:orphan:2026-10-02T01:18:36Z",
    )
    adapter = _Adapter(live=process)
    contract, state_store, intent_store, journal, runtime = _runtime(
        tmp_path,
        adapter,
    )
    intent = journal.prepare(
        contract,
        attempt=1,
        recovery_handle=adapter.prepare_start_recovery(
            contract,
            intent_id="seed",
            attempt=1,
        ),
    )
    journal.record_process(intent, process)

    before = runtime.inspect_quiescence_exact(contract)
    assert not before.quiescent

    outcome = runtime.quiesce_exact(contract)

    assert outcome.quiescent
    assert adapter.stopped == [process]
    assert journal.unresolved(contract) is None
    state = state_store.read()
    assert state.phase is ServicePhase.EXITED
    assert state.process is None


def test_quiesce_aborts_prepared_start_proven_not_started(
    tmp_path: Path,
) -> None:
    adapter = _Adapter(
        prepared_status=PreparedServiceStartStatus.NOT_STARTED,
    )
    contract, state_store, intent_store, journal, runtime = _runtime(
        tmp_path,
        adapter,
    )
    journal.prepare(
        contract,
        attempt=1,
        recovery_handle=adapter.prepare_start_recovery(
            contract,
            intent_id="seed",
            attempt=1,
        ),
    )

    outcome = runtime.quiesce_exact(contract)

    assert outcome.quiescent
    assert adapter.stopped == []
    assert journal.unresolved(contract) is None
    assert state_store.read().phase is ServicePhase.EXITED


def test_quiesce_fails_closed_when_prepared_start_is_unknown(
    tmp_path: Path,
) -> None:
    adapter = _Adapter(
        prepared_status=PreparedServiceStartStatus.UNKNOWN,
    )
    contract, state_store, intent_store, journal, runtime = _runtime(
        tmp_path,
        adapter,
    )
    journal.prepare(
        contract,
        attempt=1,
        recovery_handle=adapter.prepare_start_recovery(
            contract,
            intent_id="seed",
            attempt=1,
        ),
    )

    with pytest.raises(
        ServiceQuiescenceRecoveryRequired,
        match="not safely quiescent",
    ):
        runtime.quiesce_exact(contract)

    assert journal.unresolved(contract) is not None
    assert state_store.read().phase is ServicePhase.START_CHILD


def _completed_start_effect(
    journal: ServiceStartEffectJournal,
    contract: ServiceLaunchContract,
    process: ServiceProcessIdentity,
) -> None:
    intent = journal.prepare(contract, attempt=1, recovery_handle=None)
    intent = journal.record_process(intent, process)
    intent = journal.state_committed(intent)
    journal.complete(intent)


def test_quiescence_does_not_infer_physical_absence_from_missing_state(
    tmp_path: Path,
) -> None:
    contract = _contract()
    process = ServiceProcessIdentity(902, "docker:live-after-state-loss")
    adapter = _Adapter(live=process)
    state_store = FileServiceStateStore(tmp_path / "missing-state.json")
    journal = ServiceStartEffectJournal(
        sqlite_effect_intent_journal(tmp_path / "missing-state-effects.sqlite3")
    )
    _completed_start_effect(journal, contract, process)
    runtime = ExactServiceRuntimeEndpoint(
        build_service_supervisor(state_store, journal, adapter)
    )

    before = runtime.inspect_quiescence_exact(contract)
    assert not before.quiescent
    assert "still live" in before.summary

    outcome = runtime.quiesce_exact(contract)
    assert outcome.quiescent
    assert adapter.stopped == [process]
    assert state_store.read().phase is ServicePhase.EXITED
    assert state_store.read().process is None


def test_quiescence_does_not_infer_physical_absence_from_exited_projection(
    tmp_path: Path,
) -> None:
    contract = _contract()
    process = ServiceProcessIdentity(903, "docker:live-after-exited-projection")
    adapter = _Adapter(live=process)
    state_store = FileServiceStateStore(tmp_path / "exited-state.json")
    initial = ServiceSupervisorState.initial(contract.service_id, contract.digest())
    state_store.write(replace(initial, phase=ServicePhase.EXITED, process=None))
    journal = ServiceStartEffectJournal(
        sqlite_effect_intent_journal(tmp_path / "exited-state-effects.sqlite3")
    )
    _completed_start_effect(journal, contract, process)
    runtime = ExactServiceRuntimeEndpoint(
        build_service_supervisor(state_store, journal, adapter)
    )

    before = runtime.inspect_quiescence_exact(contract)
    assert not before.quiescent
    assert "still live" in before.summary

    outcome = runtime.quiesce_exact(contract)
    assert outcome.quiescent
    assert adapter.stopped == [process]
    final = state_store.read()
    assert final.phase is ServicePhase.EXITED
    assert final.process is None
