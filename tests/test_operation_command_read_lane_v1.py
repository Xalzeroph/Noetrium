"""Scientific operation snapshots and command evidence never block durable effects."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from noetrium_platform.research.execution.operation.api import CommandId, OperationId
from noetrium_platform.research.execution.operation.command.providers import SQLiteCommandStore
from noetrium_platform.research.execution.operation.providers import SQLiteOperationStore
from noetrium_platform.research.execution.operation.runtime import OperationOwner
from tests.test_durable_execution_command_v1 import _command


def _verify_independent_read(store, read, expect):
    held, release=Event(), Event()
    def hold_writer():
        with store._connections.session() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                held.set()
                assert release.wait(3)
            finally:
                db.rollback()
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            owner=workers.submit(hold_writer)
            assert held.wait(2)
            try:
                assert workers.submit(read).result(timeout=.7)==expect
            finally:
                release.set()
            owner.result(timeout=2)
        assert store._readers.open_count==1
    finally:
        release.set();store.close()


def test_command_authority_frozen_lookup_is_independent_of_write_permit(tmp_path):
    store=SQLiteCommandStore(tmp_path/'commands.sqlite3')
    committed,_=store.create_or_get(_command())
    _verify_independent_read(store,lambda:store.load(CommandId('cmd-1')),committed)


def test_operation_authority_state_lookup_is_independent_of_write_permit(tmp_path):
    store=SQLiteOperationStore(tmp_path/'operations.sqlite3')
    created,_=OperationOwner(store).submit(
        CommandId('cmd-1'),operation_id=OperationId('op-1'),now_unix=10.,
    )
    _verify_independent_read(store,lambda:store.load(OperationId('op-1')),created)
