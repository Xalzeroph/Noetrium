from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import noetrium_platform.foundation.kernel.kernel.journal as journal_module
from noetrium_platform.foundation.kernel.kernel import DirectoryMachineJournal
from tests.test_machine_journal_scale_v1 import _commit


def test_distinct_machines_encode_state_outside_process_wide_cache_lock(tmp_path, monkeypatch) -> None:
    journal = DirectoryMachineJournal(tmp_path)
    machine_ids = ("parallel-machine-a", "parallel-machine-b")
    previous: dict[str, str] = {}
    for machine_id in machine_ids:
        first = _commit(1, previous_commit_id=None, machine_id=machine_id)
        journal.append(first)
        previous[machine_id] = first.commit_id

    barrier = Barrier(2, timeout=2.0)
    seen: set[str] = set()
    guard = Lock()
    original = journal_module._commit_document

    def observed(commit, *, previous_state, force_snapshot):
        should_wait = False
        if commit.revision == 2 and not force_snapshot and commit.machine_id in machine_ids:
            with guard:
                if commit.machine_id not in seen:
                    seen.add(commit.machine_id)
                    should_wait = True
        if should_wait:
            barrier.wait()
        return original(commit, previous_state=previous_state, force_snapshot=force_snapshot)

    monkeypatch.setattr(journal_module, "_commit_document", observed)

    def append_second(machine_id: str):
        second = _commit(
            2,
            previous_commit_id=previous[machine_id],
            machine_id=machine_id,
        )
        return journal.append(second)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(append_second, machine_ids))

    assert {row.machine_id for row in results} == set(machine_ids)
    assert seen == set(machine_ids)
    assert all(journal.latest(machine_id).revision == 2 for machine_id in machine_ids)
