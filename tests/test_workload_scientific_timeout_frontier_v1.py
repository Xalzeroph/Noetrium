"""Workload frontier preserves task-level scientific timeouts as durable failures."""
import unittest
import time
from types import SimpleNamespace

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskDeadlineExceeded
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.experimentation.lifecycle.study.api import assignment_workload
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_unit
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadTaskDeadlineExceeded, WorkloadTaskPartialMeasurement,
)
from noetrium_platform.research.experimentation.workload.runtime.graph import (
    WorkloadGraphBinding, _WorkloadExecutionBinding,
)


class _Scientific:
    cancelled = False
    reason = None
    deadline = None
    remaining_seconds = None
    scientific_time_active = False
    scientific_deadline = None

    def activate_scientific_time(self):
        self.scientific_time_active = True

    def checkpoint(self):
        pass

    def subscribe_cancel(self, callback):
        return lambda: None

    def wait(self, timeout=None):
        return False


class _TimeoutExecutor:
    def execute_one(self, task, context, control):
        control.activate_scientific_time()
        control._deadline = Deadline(time.monotonic() - 1.0)
        raise TaskDeadlineExceeded("workload execution budget exceeded: task")


class ScientificTimeoutFrontierTests(unittest.TestCase):
    def test_one_expired_scientific_task_settles_without_cancelling_entire_workload(self):
        task_id = "task-scientific-timeout"
        task = task_unit(
            task_id, revision_id="1", family="mock", schema_id="test.task.v1",
            content_digest=None, content={"goal": "execute"},
        )
        workload = assignment_workload((task_id,))
        context = ExecutionContext("run", "trace", "span", trial_budget={"max_seconds": 10})
        control = _Scientific()
        binding = _WorkloadExecutionBinding(
            by_id={task_id: task}, workload=workload,
            context=context, control=control,
            ordinal_by_id={task_id: 0}, task_group=None,
        )
        graph = object.__new__(WorkloadGraphBinding)
        graph._workload = _TimeoutExecutor()
        handle = graph._frontier_handler(
            by_id=binding.by_id, workload=workload, context=context,
            control=control, ordinal_by_id=binding.ordinal_by_id,
            task_group=None,
        )
        handle(SimpleNamespace(semantic_state={}), binding)
        results = binding.completed_results
        self.assertIsNotNone(results)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertFalse(result.success)
        self.assertEqual(result.failure_scope, "task")
        self.assertTrue(result.diagnostics["scientific_censored"])
        self.assertTrue(result.diagnostics["step_count_unobserved"])
        self.assertFalse(result.diagnostics["partial_measurement_observed"])
        self.assertIn("execution budget exceeded", result.failure_reason)

    def test_scientific_timeout_preserves_already_observed_partial_measurement(self):
        class _MeasuredTimeoutExecutor:
            def execute_one(self, task, context, control):
                control.activate_scientific_time()
                control._deadline = Deadline(time.monotonic() - 1.0)
                raise WorkloadTaskDeadlineExceeded(
                    "workload execution budget exceeded: measured-task",
                    partial_measurement=WorkloadTaskPartialMeasurement(
                        steps=7,
                        diagnostics={
                            "model_tokens": 33,
                            "physical_child_effects": 2,
                            "partial_measurement_source": "fixture-journal",
                        },
                    ),
                )

        task_id = "task-scientific-timeout-measured"
        task = task_unit(
            task_id, revision_id="1", family="mock", schema_id="test.task.v1",
            content_digest=None, content={"goal": "execute"},
        )
        workload = assignment_workload((task_id,))
        context = ExecutionContext(
            "run-measured", "trace", "span", trial_budget={"max_seconds": 10}
        )
        control = _Scientific()
        binding = _WorkloadExecutionBinding(
            by_id={task_id: task}, workload=workload,
            context=context, control=control, ordinal_by_id={task_id: 0},
            task_group=None,
        )
        graph = object.__new__(WorkloadGraphBinding)
        graph._workload = _MeasuredTimeoutExecutor()
        handle = graph._frontier_handler(
            by_id=binding.by_id, workload=workload, context=context,
            control=control, ordinal_by_id=binding.ordinal_by_id,
            task_group=None,
        )
        handle(SimpleNamespace(semantic_state={}), binding)
        result = binding.completed_results[0]
        self.assertFalse(result.success)
        self.assertEqual(result.steps, 7)
        self.assertEqual(result.diagnostics["model_tokens"], 33)
        self.assertEqual(result.diagnostics["physical_child_effects"], 2)
        self.assertTrue(result.diagnostics["scientific_censored"])
        self.assertFalse(result.diagnostics["step_count_unobserved"])
        self.assertTrue(result.diagnostics["partial_measurement_observed"])
        self.assertEqual(
            result.diagnostics["partial_measurement_source"], "fixture-journal"
        )


    def test_raw_admission_timeout_is_scientifically_censored_only_after_budget_expiry(self):
        class _AdmissionTimeoutExecutor:
            def execute_one(self, task, context, control):
                control.activate_scientific_time()
                control._deadline = Deadline(time.monotonic() - 1.0)
                raise TimeoutError("execution admission deadline expired")

        task_id = "task-admission-timeout-after-scientific-expiry"
        task = task_unit(
            task_id, revision_id="1", family="mock", schema_id="test.task.v1",
            content_digest=None, content={"goal": "execute"},
        )
        workload = assignment_workload((task_id,))
        context = ExecutionContext("run-admission", "trace", "span", trial_budget={"max_seconds": 10})
        control = _Scientific()
        binding = _WorkloadExecutionBinding(
            by_id={task_id: task}, workload=workload, context=context, control=control,
            ordinal_by_id={task_id: 0}, task_group=None,
        )
        graph = object.__new__(WorkloadGraphBinding)
        graph._workload = _AdmissionTimeoutExecutor()
        handle = graph._frontier_handler(
            by_id=binding.by_id, workload=workload, context=context, control=control,
            ordinal_by_id=binding.ordinal_by_id, task_group=None,
        )
        handle(SimpleNamespace(semantic_state={}), binding)
        result = binding.completed_results[0]
        self.assertEqual(result.failure_scope, "task")
        self.assertTrue(result.diagnostics["scientific_censored"])
        self.assertEqual(
            result.diagnostics["deadline_detection_source"],
            "execution_control_checkpoint_after_timeout",
        )
        self.assertEqual(result.diagnostics["deadline_trigger_type"], "TimeoutError")

    def test_raw_infrastructure_timeout_before_scientific_expiry_is_not_relabelled(self):
        class _InfrastructureTimeoutExecutor:
            def execute_one(self, task, context, control):
                control.activate_scientific_time()
                raise TimeoutError("execution admission deadline expired")

        task_id = "task-infrastructure-timeout-before-scientific-expiry"
        task = task_unit(
            task_id, revision_id="1", family="mock", schema_id="test.task.v1",
            content_digest=None, content={"goal": "execute"},
        )
        workload = assignment_workload((task_id,))
        context = ExecutionContext("run-infra", "trace", "span", trial_budget={"max_seconds": 10})
        control = _Scientific()
        binding = _WorkloadExecutionBinding(
            by_id={task_id: task}, workload=workload, context=context, control=control,
            ordinal_by_id={task_id: 0}, task_group=None,
        )
        graph = object.__new__(WorkloadGraphBinding)
        graph._workload = _InfrastructureTimeoutExecutor()
        handle = graph._frontier_handler(
            by_id=binding.by_id, workload=workload, context=context, control=control,
            ordinal_by_id=binding.ordinal_by_id, task_group=None,
        )
        with self.assertRaisesRegex(TimeoutError, "execution admission deadline expired"):
            handle(SimpleNamespace(semantic_state={}), binding)


if __name__ == "__main__":
    unittest.main()
