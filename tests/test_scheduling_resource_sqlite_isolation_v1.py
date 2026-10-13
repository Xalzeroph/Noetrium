"""One shared scheduler journal, isolated from resource effects' SQLite writer."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Event
from types import SimpleNamespace

from noetrium_platform.composition.concurrency import build_scheduling_authority


def test_resource_and_global_scheduling_have_distinct_transaction_permits(tmp_path):
    resource_path = tmp_path / 'platform-resources.sqlite'
    resource_path.touch()
    resource = SimpleNamespace(path=resource_path)
    first = build_scheduling_authority(resource_authority=resource)
    second = build_scheduling_authority(resource_authority=resource)
    try:
        assert first._ledger_path == second._ledger_path
        assert first._ledger_path != resource_path
        assert first._ledger_path.parent == resource_path.parent
        with sqlite3.connect(resource_path, timeout=.1, isolation_level=None) as held:
            held.execute('BEGIN IMMEDIATE')
            try:
                # A physically blocked claim in Resource Authority's DB must
                # not consume the Scheduling Authority's independent permit.
                with ThreadPoolExecutor(max_workers=1) as workers:
                    grant = workers.submit(
                        first.record_grant, tenant_id='paper-1', flow_id='flow-1',
                    )
                    assert grant.result(timeout=2) == 1
                    complete = workers.submit(
                        first.record_completion, tenant_id='paper-1',
                        flow_id='flow-1', service_quanta=5,
                    )
                    assert complete.result(timeout=2) is None
            finally:
                held.execute('ROLLBACK')
        assert second.service_revision() == 2
        assert second._flow_states[second._flow_key('paper-1', None, 'flow-1')].service_quanta == 5
    finally:
        first.close()
        second.close()
