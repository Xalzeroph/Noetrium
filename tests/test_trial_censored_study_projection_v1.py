"""Censored measurement truth survives Trial -> Study -> MetricEngine."""
import unittest
from dataclasses import replace

from noetrium_platform.foundation.kernel.structure import structure_unit
from noetrium_platform.foundation.governance.api import ScopeKind, scope_unit
from noetrium_platform.research.execution.api import ArtifactReference
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    assignment_workload, study_assignment, study_protocol, StudyMetricObservation,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.trial import TrialExecutionReceipt
from noetrium_platform.research.experimentation.projection import evaluate_study_metric_aggregates
from noetrium_platform.research.experimentation.api.program import _observation_json, _observation_from_json


class CensoredStudyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.workload = assignment_workload(("task-a",))
        self.protocol = study_protocol(
            study_id="study-a", workload_id="test-workload",
            variant_space=structure_unit(
                "one-variant",
                traits=("study.variant-space",),
                parameters={"variant_count":1,"implementation_id":"test-variant"},
            ),
            repetitions=2, seed_schedule_digest="a"*64,
            metric_names=("success_rate", "memory_calls_total"),
            task_manifest_digest="b"*64,
            assignment_workloads=(self.workload,), budget_tiers=(),
        )
        self.reference = ArtifactReference(
            "trial-ref", scope_unit(ScopeKind.RUN, "test-run"),
            "trial-artifact", 1,
        )

    def observation(self, repetition, success, memory=None):
        assignment = study_assignment(
            study_id="study-a", variant_id="variant-a", variant_index=0,
            repetition=repetition, seed=f"seed-{repetition}",
            workload=self.workload,
        )
        metrics = (("success_rate", float(success)),)
        if memory is not None:
            metrics += (("memory_calls_total", float(memory)),)
        return StudyMetricObservation(
            assignment, metrics, trial_request_digest="c"*64,
            trial_receipt_digest="d"*64,
            trial_receipt_reference=self.reference,
            unobserved_metric_names=(
                ("memory_calls_total",) if memory is None else ()
            ),
        )

    def test_partial_study_projection_retains_denominators(self):
        censored = self.observation(0, 0)
        complete = self.observation(1, 1, 3)
        self.assertEqual(
            _observation_from_json(_observation_json(censored)),
            censored,
        )
        result = evaluate_study_metric_aggregates(
            self.protocol, (censored, complete),
            expected_assignment_count=2,
        )
        pairs = {(row.metric_name, row.variant_id):row for row in result}
        self.assertEqual(pairs[("success_rate","variant-a")].count, 2)
        self.assertEqual(pairs[("success_rate","variant-a")].mean, 0.5)
        self.assertEqual(pairs[("memory_calls_total","variant-a")].count, 1)
        self.assertEqual(pairs[("memory_calls_total","variant-a")].mean, 3.0)

    def test_missing_metrics_fail_without_authoritative_missing_declaration(self):
        censored = self.observation(0,0)
        with self.assertRaises(ValueError):
            evaluate_study_metric_aggregates(
                self.protocol, (replace(censored,unobserved_metric_names=()),),
                expected_assignment_count=1,
            )

    def test_trial_disallows_claiming_observed_and_unobserved_together(self):
        receipt = TrialExecutionReceipt(
            request_digest="c"*64, assignment_digest="d"*64,
            measurements=(), unobserved_measurement_ids=("memory_calls_total",),
        )
        self.assertEqual(receipt.unobserved_measurement_ids,("memory_calls_total",))
        with self.assertRaises(ValueError):
            TrialExecutionReceipt(
                request_digest="c"*64, assignment_digest="d"*64,
                measurements=(),
                unobserved_measurement_ids=("missing","missing"),
            )


if __name__=="__main__":
    unittest.main()
