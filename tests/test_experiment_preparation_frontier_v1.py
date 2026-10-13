from __future__ import annotations

from queue import Queue

from noetrium_platform.foundation.kernel.concurrency.api import (
    UNBOUNDED_EXECUTION_CONTROL,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.experimentation.api.program import (
    ExperimentProgramBinding,
)
from noetrium_platform.foundation.kernel.structure import structure_unit
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    assignment_workload, study_protocol,
)


class _Handle:
    def result(self):
        raise AssertionError("frontier test must not execute fake handles")

    def cancel(self) -> bool:
        return True


class _RecordingTaskGroup:
    def __init__(self, *, reject_try_after: int | None = None) -> None:
        self.submitted: list[str] = []
        self.tried: list[str] = []
        self._reject_try_after = reject_try_after

    def submit(self, spec, fn, /, *args, **kwargs):
        del fn, args, kwargs
        self.submitted.append(spec.task_id)
        return _Handle()

    def try_submit(self, spec, fn, /, *args, **kwargs):
        del fn, args, kwargs
        if (
            self._reject_try_after is not None
            and len(self.tried) >= self._reject_try_after
        ):
            return None
        self.tried.append(spec.task_id)
        return _Handle()


def _binding(task_group):
    binding = object.__new__(ExperimentProgramBinding)
    binding.task_group = task_group
    binding._study_protocol = study_protocol(
        study_id="frontier.test", workload_id="independent-trials",
        variant_space=structure_unit(
            "single-variant", traits=("study.variant-space",),
            parameters={"variant_count":1,"implementation_id":"fake"},
        ),
        repetitions=1, seed_schedule_digest="a"*64,
        metric_names=(), task_manifest_digest="b"*64,
        assignment_workloads=tuple(
            assignment_workload((f"trial-{i}",)) for i in range(16)
        ),
        budget_tiers=(),
    )
    binding.execution_context = ExecutionContext(
        run_id="a" * 64,
        trace_id="trace",
        span_id="span",
    )
    binding.execution_control = UNBOUNDED_EXECUTION_CONTROL
    binding._frontier_completion = Queue()
    binding._frontier_active = {}
    binding._frontier_invocation = "test-frontier"
    return binding


def test_frontier_offers_ready_assignments_until_shared_authority_declines() -> None:
    group = _RecordingTaskGroup(reject_try_after=2)
    binding = _binding(group)

    binding._refill_frontier(
        total=16,
        completed_prefix=0,
        completed_sparse=set(),
    )

    assert sorted(binding._frontier_active) == [0, 1, 2]
    assert len(group.submitted) == 1
    assert len(group.tried) == 2


def test_frontier_stops_at_shared_nonblocking_admission() -> None:
    group = _RecordingTaskGroup(reject_try_after=1)
    binding = _binding(group)
    binding._refill_frontier(
        total=16,
        completed_prefix=1,
        completed_sparse=set(),
    )

    assert sorted(binding._frontier_active) == [1, 2]
    assert len(group.submitted) == 1
    assert len(group.tried) == 1
