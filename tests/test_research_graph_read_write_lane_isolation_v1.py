"""Research graph read snapshots cannot monopolize physical writer leases."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Event

import pytest

from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)
from tests._execution_graph_fixtures import (
    materialize_execution,
    scheduling_graph,
    scheduling_vertex,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _store(tmp_path):
    store = SQLiteResearchGraphExecutionStore(tmp_path / 'graph.sqlite3')
    plan = scheduling_graph(
        'independent-read-writer-lanes', canonical_digest({'rev': 1}),
        (scheduling_vertex('alpha',canonical_digest({'alpha': 1})),),
    )
    materialize_execution(store, 'paper-exec', plan)
    return store


def test_reads_proceed_while_writer_owns_priority_gate(tmp_path):
    store = _store(tmp_path)
    entered, release = Event(), Event()
    def hold_writer():
        with store._writer_connection():
            entered.set()
            assert release.wait(3)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            held = workers.submit(hold_writer)
            assert entered.wait(2)
            try:
                result = workers.submit(store.control_state, 'paper-exec')
                assert result.result(timeout=.7).execution_id == 'paper-exec'
                assert store._readers.open_count == 1
            finally:
                release.set()
            held.result(timeout=2)
    finally:
        release.set();store.close()


def test_writes_proceed_while_read_snapshot_remains_open(tmp_path):
    store=_store(tmp_path)
    entered, release = Event(), Event()
    def hold_read():
        with store._connection() as conn:
            assert conn.execute('SELECT COUNT(*) FROM research_graph_nodes').fetchone()[0] == 1
            entered.set()
            assert release.wait(3)
            assert conn.execute('SELECT COUNT(*) FROM research_graph_nodes').fetchone()[0] == 1
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            held=workers.submit(hold_read)
            assert entered.wait(2)
            try:
                marked=workers.submit(store.mark_ready,'paper-exec','alpha',now_ns=1)
                assert marked.result(timeout=.7).node_id == 'alpha'
            finally:
                release.set()
            held.result(timeout=2)
        assert store.node_state('paper-exec','alpha').state.value == 'ready'
    finally:
        release.set();store.close()


def test_read_only_snapshot_refuses_projection_mutation(tmp_path):
    import sqlite3
    store=_store(tmp_path)
    try:
        with store._connection() as conn:
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                conn.execute('DELETE FROM research_graph_nodes')
    finally:
        store.close()
