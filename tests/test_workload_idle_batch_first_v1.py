from types import SimpleNamespace

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.experimentation.lifecycle.study.api import assignment_workload
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_unit, task_id as task_unit_id
from noetrium_platform.research.experimentation.workload.api import WorkloadTaskResult
from noetrium_platform.research.experimentation.workload.runtime.graph import WorkloadGraphBinding, _WorkloadExecutionBinding
from tests.test_workload_scientific_timeout_frontier_v1 import _Scientific


class _Executor:
    def execute_one(self, task, context, control):
        del context, control
        semantic_id = task_unit_id(task)
        return WorkloadTaskResult(
            task_id=semantic_id, family="mock", complete=True, success=True,
            utility=1.0, steps=1, duration_s=0.0, lineage_id=semantic_id,
            failure_reason="",
        )


class _Handle:
    def __init__(self, value):
        self._value = value

    def result(self, timeout=None):
        del timeout
        return self._value

    def cancel(self):
        return False


class _Group:
    def __init__(self, control, *, deny_first_batch=False):
        self.control = control
        self.deny_first_batch = deny_first_batch
        self.batch_calls = []
        self.submit_calls = 0

    def _run(self, pair):
        _spec, fn = pair
        return _Handle(fn(self.control))

    def try_submit_maximal_batch(self, items, *, deadline=None):
        del deadline
        self.batch_calls.append(len(items))
        if self.deny_first_batch:
            self.deny_first_batch = False
            return ()
        return tuple(self._run(pair) for pair in items)

    def submit(self, spec, fn, *, deadline=None):
        del spec, deadline
        self.submit_calls += 1
        return _Handle(fn(self.control))


def _drive(*, deny_first_batch=False):
    names = ("a", "b", "c")
    tasks = tuple(task_unit(
        name, revision_id="1", family="mock", schema_id="mock.v1",
        content_digest=None, content={"goal": "test"},
    ) for name in names)
    workload = assignment_workload(names)
    context = ExecutionContext("run", "trace", "span")
    control = _Scientific()
    group = _Group(control, deny_first_batch=deny_first_batch)
    binding = _WorkloadExecutionBinding(
        by_id=dict(zip(names, tasks)), workload=workload,
        context=context, control=control,
        ordinal_by_id=dict(zip(names, range(len(names)))), task_group=group,
    )
    graph = object.__new__(WorkloadGraphBinding)
    graph._workload = _Executor()
    handler = graph._frontier_handler(
        by_id=binding.by_id, workload=workload, context=context,
        control=control, ordinal_by_id=binding.ordinal_by_id,
        task_group=group,
    )
    semantic = {}
    for _ in range(8):
        transition = handler(SimpleNamespace(semantic_state=semantic), binding)
        semantic.update(dict(transition.state.semantic))
        if binding.completed_results is not None:
            break
    assert binding.completed_results is not None
    return group, binding.completed_results


def test_idle_ready_frontier_uses_one_maximal_batch_before_blocking_submit():
    group, results = _drive()
    assert group.batch_calls == [3]
    assert group.submit_calls == 0
    assert {result.task_id for result in results} == {"a", "b", "c"}


def test_idle_frontier_falls_back_to_one_blocking_submit_only_after_batch_denial():
    group, results = _drive(deny_first_batch=True)
    assert group.batch_calls == [3, 2]
    assert group.submit_calls == 1
    assert all(result.success for result in results)
