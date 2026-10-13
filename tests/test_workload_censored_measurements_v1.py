"""Unobserved metrics from a scientifically timed-out task are not zeros."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from tests_support import measurement_for_test
from noetrium_platform.research.experimentation.workload.api import WorkloadTaskResult
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    StandardWorkloadMeasurementProjection as Projection,
)


class CensoredWorkloadMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.censored = WorkloadTaskResult(
            task_id="timeout", family="bench", complete=False, success=False, utility=0.0,
            steps=0, duration_s=240.4, lineage_id="timeout",
            failure_reason="workload execution budget exceeded",
            diagnostics={
                "scientific_censored": True, "step_count_unobserved": True,
                "cause_type": "TaskDeadlineExceeded",
            },
        )
        self.completed = WorkloadTaskResult(
            task_id="completed", family="bench", complete=True, success=True, utility=1.0,
            steps=4, duration_s=4.0, lineage_id="completed",
            exports={"result": {"memory_calls_total": 3}},
        )

    def definition(self, name, source):
        return measurement_for_test(
            name, semantic_kind=name, source_path=source, reducer="sum",
        )

    def test_timeout_has_valid_success_utility_and_duration_but_unknown_steps(self):
        rows = (self.censored, self.completed)
        for source in ("success", "utility", "duration_s"):
            self.assertFalse(Projection._censored_source_missing(
                self.definition(source, source), rows,
            ))
        self.assertTrue(Projection._censored_source_missing(
            self.definition("steps_total", "steps"), rows,
        ))
        self.assertTrue(Projection._censored_source_missing(
            self.definition("memory_calls_total", "exports.result.memory_calls_total"),
            rows,
        ))

    def test_successful_producer_remains_measured_and_missing_sources_fail_closed(self):
        completed = (self.completed,)
        self.assertFalse(Projection._censored_source_missing(
            self.definition("memory_calls_total", "exports.result.memory_calls_total"),
            completed,
        ))
        self.assertTrue(Projection._source_exists(
            self.completed, "exports.result.memory_calls_total",
        ))
        self.assertFalse(Projection._source_exists(
            self.censored, "exports.result.memory_calls_total",
        ))
        with self.assertRaises(KeyError):
            Projection._declared_value(
                self.definition("memory_calls_total", "exports.result.memory_calls_total"),
                (self.censored,),
            )

    def test_terminal_action_envelope_is_not_a_final_method_result(self):
        path = "exports.participants.paper_agent.result.memory_calls_total"
        definition = self.definition("memory_calls_total", path)
        # Mimics v71's durable failed participant: a real participant receipt,
        # but only the last action envelope, not a final Method result.
        def row(*, success, result):
            return SimpleNamespace(
                success=success, diagnostics={},
                participant_receipts=(("paper_agent", object()),),
                completion_receipt=None,
                exports={"participants": {"paper_agent": {"result": result}}},
            )
        action = row(
            success=False,
            result={"action_type": "collect_block", "payload": {"block": "oak_log"}},
        )
        self.assertTrue(Projection._censored_source_missing(definition, (action,)))
        # Preserve fail-close for a final Method result with a missing field.
        final_incomplete = row(
            success=False,
            result={"task_id": "task", "success": False, "method": "example"},
        )
        self.assertFalse(Projection._censored_source_missing(
            definition, (final_incomplete,),
        ))
        with self.assertRaises(KeyError):
            Projection._declared_value(definition, (final_incomplete,))
        completed = row(
            success=True, result={"action_type": "collect_block", "payload": {}},
        )
        self.assertFalse(Projection._censored_source_missing(
            definition, (completed,),
        ))

    def test_failed_method_exports_do_not_fabricate_missing_memory_counts(self):
        failed = SimpleNamespace(
            success=False, diagnostics={},
            participant_receipts=(
                ("paper_agent", SimpleNamespace(status="failed")),
            ),
            completion_receipt=None,
            exports={
                "participants": {
                    "paper_agent": {
                        "result": {
                            "task_id": "failed", "action_type": "collect_block"
                        }
                    }
                }
            },
        )
        definition = self.definition(
            "active_node_count",
            "exports.participants.paper_agent.result.active_node_count",
        )
        self.assertTrue(
            Projection._censored_source_missing(definition, (failed,))
        )
        successful = SimpleNamespace(
            success=True, diagnostics={},
            participant_receipts=(
                ("paper_agent", SimpleNamespace(status="succeeded")),
            ),
            completion_receipt=None,
            exports=failed.exports,
        )
        self.assertFalse(
            Projection._censored_source_missing(definition, (successful,))
        )

    def test_unassessed_participant_failure_keeps_counters_unobserved(self):
        # Durable parent-machine failure may already have been converted to
        # a task result before reaching the Workload frontier. No Method
        # receipt exists, so step counts and memory exports are not observed.
        unassessed = replace(
            self.censored,
            diagnostics={},
            failure_reason="participant parent machine stopped with failed",
        )
        self.assertTrue(Projection._censored_source_missing(
            self.definition("memory_calls_total", "exports.result.memory_calls_total"),
            (unassessed,),
        ))
        self.assertTrue(Projection._censored_source_missing(
            self.definition("steps_total", "steps"), (unassessed,),
        ))
        self.assertFalse(Projection._censored_source_missing(
            self.definition("success_rate", "success"), (unassessed,),
        ))
        self.assertFalse(Projection._censored_source_missing(
            self.definition("duration_s", "duration_s"), (unassessed,),
        ))


if __name__ == "__main__":
    unittest.main()
