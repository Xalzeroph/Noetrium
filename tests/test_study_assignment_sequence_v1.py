"""Scientific assignment ordering: settled predecessors, independent cohorts."""
import unittest

from noetrium_platform.foundation.kernel.structure import structure_unit
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    assignment_workload, study_protocol,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    study_protocol_assignment_relations,
)
from noetrium_platform.research.experimentation.api.program import (
    _ready_assignment_indexes,
)


class StudyAssignmentCausalityTests(unittest.TestCase):
    def setUp(self):
        variant_space = structure_unit(
            "space", traits=("study.variant-space",),
            parameters={"variant_count": 2, "implementation_id": "test.method"},
        )
        self.protocol = study_protocol(
            study_id="study.causality",
            workload_id="causal-memory-stream",
            variant_space=variant_space,
            repetitions=2,
            seed_schedule_digest="a" * 64,
            metric_names=("success_rate",),
            task_manifest_digest="b" * 64,
            assignment_workloads=(
                assignment_workload(("task-1",)),
                assignment_workload(("task-2",)),
                assignment_workload(("task-3",)),
            ),
            budget_tiers=(),
            assignment_relations=(
                (0, 1, "sequence_after"),
                (1, 2, "sequence_after"),
            ),
        )

    def ready(self, prefix=0, sparse=(), active=()):
        return _ready_assignment_indexes(
            self.protocol,
            total=12,  # 2 repeats × 2 variants × 3 tasks
            completed_prefix=prefix,
            completed_sparse=set(sparse),
            active_indexes=set(active),
        )

    def test_independent_repetitions_and_variants_admitted_concurrently(self):
        self.assertEqual(self.ready(), (0, 3, 6, 9))
        self.assertEqual(self.ready(active=(0, 3, 6, 9)), ())

    def test_failed_predecessor_settlement_releases_only_its_successor(self):
        # Sparse completion is the durable Experiment observation, irrespective
        # of task success. No completed Trial is allowed to be ignored.
        self.assertEqual(self.ready(sparse=(0,)), (1, 3, 6, 9))
        self.assertEqual(self.ready(prefix=1, sparse=(3,)), (1, 4, 6, 9))
        self.assertEqual(self.ready(sparse=(0, 1)), (2, 3, 6, 9))
        self.assertEqual(self.ready(prefix=3), (3, 6, 9))

    def test_scientific_sequence_is_canonical_and_invalid_edges_fail_closed(self):
        self.assertEqual(
            study_protocol_assignment_relations(self.protocol),
            ((0, 1, "sequence_after"), (1, 2, "sequence_after")),
        )
        from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import study_protocol
        kwargs = dict(
            study_id="invalid", workload_id="w",
            variant_space=structure_unit(
                "space-2", traits=("study.variant-space",),
                parameters={"variant_count":1,"implementation_id":"test.method"},
            ),
            repetitions=1, seed_schedule_digest="a"*64,
            metric_names=(), task_manifest_digest="b"*64,
            assignment_workloads=(assignment_workload(("a",)), assignment_workload(("b",))),
            budget_tiers=(),
        )
        for relations in (((1, 0, "sequence_after"),),
                          ((0, 1, "prerequisite"),),
                          ((0, 1, "sequence_after"), (0, 1, "sequence_after"))):
            with self.subTest(relations=relations), self.assertRaises(ValueError):
                study_protocol(**kwargs, assignment_relations=relations)


if __name__ == "__main__":
    unittest.main()
