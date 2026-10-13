"""Success-gated prerequisites and completion-gated learning sequences differ."""
import unittest
from types import SimpleNamespace

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    TaskRelation, assignment_workload, task_graph, task_graph_relation,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_unit, task_id as task_unit_id
from noetrium_platform.research.experimentation.workload.api import WorkloadTaskResult
from noetrium_platform.research.experimentation.workload.runtime.graph import (
    WorkloadGraphBinding, _WorkloadExecutionBinding,
)

from tests.test_workload_scientific_timeout_frontier_v1 import _Scientific


class _TaskExecutor:
    def __init__(self):
        self.called = []

    def execute_one(self, task, context, control):
        del control
        semantic_id = task_unit_id(task)
        self.called.append((semantic_id, context.lifetime_id))
        return WorkloadTaskResult(
            task_id=semantic_id,
            family="mock",
            complete=True,
            success=semantic_id == "second",
            utility=1.0 if semantic_id == "second" else 0.0,
            steps=1,
            duration_s=0.1,
            lineage_id=semantic_id,
            failure_reason=(
                "" if semantic_id == "second"
                else "scientific task failed after verified action"
            ),
        )


class WorkloadCompletionCausalityTests(unittest.TestCase):
    def _drive(self, relation):
        names = ("first", "second")
        tasks = tuple(task_unit(
            name, revision_id="1", family="mock", schema_id="mock.v1",
            content_digest=None, content={"goal": "test"},
        ) for name in names)
        workload = assignment_workload(
            names, task_graph((task_graph_relation("first","second",relation),)),
        )
        context = ExecutionContext("run", "trace", "span")
        control = _Scientific()
        binding = _WorkloadExecutionBinding(
            by_id=dict(zip(names,tasks)), workload=workload,
            context=context, control=control,
            ordinal_by_id=dict(zip(names,range(2))), task_group=None,
        )
        execution = _TaskExecutor()
        graph = object.__new__(WorkloadGraphBinding)
        graph._workload = execution
        handler = graph._frontier_handler(
            by_id=binding.by_id, workload=workload,
            context=context, control=control,
            ordinal_by_id=binding.ordinal_by_id,task_group=None,
        )
        semantic = {}
        for _ in range(4):
            transition = handler(SimpleNamespace(semantic_state=semantic),binding)
            semantic.update(dict(transition.state.semantic))
            if binding.completed_results is not None:
                break
        return execution, binding.completed_results

    def test_completion_order_runs_next_task_despite_scientific_failure(self):
        execution, results = self._drive(TaskRelation.SEQUENCE_AFTER)
        self.assertIsNotNone(results)
        self.assertEqual([r.success for r in results],[False,True])
        self.assertEqual([x[0] for x in execution.called],["first","second"])

    def test_prerequisite_still_blocks_on_failed_predecessor(self):
        execution, results = self._drive(TaskRelation.PREREQUISITE)
        self.assertIsNotNone(results)
        self.assertEqual([r.success for r in results],[False,False])
        self.assertTrue(results[1].blocked)
        self.assertEqual([x[0] for x in execution.called],["first"])


if __name__ == "__main__":
    unittest.main()
