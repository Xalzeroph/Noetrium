"""Budget read-only evidence never holds a physical budget writer permit."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.policy.api import (
    ExecutionBudgetDelta, ExecutionBudgetPolicy,
)
from noetrium_platform.research.execution.policy.runtime import (
    SQLiteExecutionBudgetAuthority,
)


def test_budget_snapshot_does_not_block_on_pending_write_cut(tmp_path):
    a = SQLiteExecutionBudgetAuthority(
        tmp_path/'budget.sqlite',
        resource_policy_digest='a'*64,
        checkpoint_replay_proof_digest='b'*64,
    )
    policy=ExecutionBudgetPolicy(
        scope_id='paper-trial',budget_id='budget',
        budget_digest=canonical_digest({'budget':'paper-trial'}),
        replay_level='observational',max_steps=12,
    )
    a.open_scope(policy)
    expected=a.snapshot(policy.scope_id)
    entered,release=Event(),Event()
    def writer():
        with a._writers.session() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                entered.set()
                assert release.wait(3)
            finally:
                db.rollback()
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            blocking=workers.submit(writer)
            assert entered.wait(2)
            try:
                assert workers.submit(a.snapshot, policy.scope_id).result(timeout=.7)==expected
            finally:
                release.set()
            blocking.result(timeout=2)
        assert a._readers.open_count == 1
    finally:
        release.set();a.close()


def test_budget_cached_reader_observes_committed_usage_from_other_owner(tmp_path):
    path=tmp_path/'budget.sqlite'
    def open_owner():
        return SQLiteExecutionBudgetAuthority(
            path,resource_policy_digest='a'*64,
            checkpoint_replay_proof_digest='b'*64,
        )
    first=open_owner();second=open_owner()
    policy=ExecutionBudgetPolicy(
        scope_id='assignment',budget_id='budget',
        budget_digest=canonical_digest({'budget':'assignment'}),
        replay_level='observational',max_steps=12,
    )
    try:
        first.open_scope(policy)
        first.activate_scope(policy.scope_id)
        assert second.snapshot(policy.scope_id).usage.steps == 0
        reserved=first.reserve(policy.scope_id,'charge-1',ExecutionBudgetDelta(steps=2))
        first.commit(reserved,ExecutionBudgetDelta(steps=2))
        assert second.snapshot(policy.scope_id).usage.steps == 2
        assert second._readers.open_count == 1
    finally:
        second.close();first.close()
