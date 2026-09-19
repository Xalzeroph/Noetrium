from __future__ import annotations

from noetrium.platform import run_method_program
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    BatchCapableRegisteredChildResearchMachineExecutor,
    ChildResearchHostRegistry,
    ThreadPoolChildResearchBatchMechanics,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from research.benchmarks.flow_practical_tasks import (
    FLOW_PRACTICAL_BENCHMARK_ID,
    FLOW_PRACTICAL_SPLIT_ID,
    build_flow_practical_task_set,
)
from research.reproductions.flow_modularized_agentic_workflow import (
    FLOW_METHOD_PROGRAM,
    FlowSubtaskBinding,
    FlowSubtaskValidationResult,
    build_flow_iclr2025_study,
    flow_average_parallelism,
    flow_dependency_complexity,
    flow_initial_state,
    flow_select_candidate,
    flow_subtask_host,
)


def _task(task_id: str, *, prev=(), next=()):
    return {
        "objective": f"Complete {task_id}",
        "agent_id": f"role-{task_id}",
        "agent": f"role-{task_id}",
        "prev": tuple(prev),
        "next": tuple(next),
        "status": "pending",
        "history": (),
        "output_format": "text",
        "data": None,
    }


def _chain():
    return {
        "a": _task("a", next=("b",)),
        "b": _task("b", prev=("a",), next=("c",)),
        "c": _task("c", prev=("b",), next=("d",)),
        "d": _task("d", prev=("c",)),
    }


def _parallel():
    return {key: _task(key) for key in ("a", "b", "c", "d")}


def _star():
    return {
        "a": _task("a", next=("b", "c", "d")),
        "b": _task("b", prev=("a",)),
        "c": _task("c", prev=("a",)),
        "d": _task("d", prev=("a",)),
    }


def _two_chains():
    return {
        "a": _task("a", next=("b",)),
        "b": _task("b", prev=("a",)),
        "c": _task("c", next=("d",)),
        "d": _task("d", prev=("c",)),
    }


def _diamond():
    return {
        "a": _task("a", next=("b", "c")),
        "b": _task("b", prev=("a",), next=("d",)),
        "c": _task("c", prev=("a",), next=("d",)),
        "d": _task("d", prev=("b", "c")),
    }


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="flow-run",
        trace_id="trace-1",
        span_id="span-1",
        study_id="flow-paper-study",
        task_id="flow-task",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


class _FlowParentAgents:
    def __init__(self) -> None:
        self.initial = [_chain(), _parallel(), _star(), _two_chains(), _diamond()]
        self.calls: list[str] = []
        self.refinements = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls.append(request.agent_id)
        if request.agent_id == "flow.workflow-initializer":
            if not self.initial:
                raise AssertionError("Flow initial workflow sequence exhausted")
            return MethodAgentResult(value=self.initial.pop(0))
        if request.agent_id == "flow.workflow-refiner":
            self.refinements += 1
            return MethodAgentResult(value={})
        if request.agent_id == "flow.summary":
            return MethodAgentResult(value={"summary": "final synthesized output"})
        raise AssertionError(f"unexpected Flow parent agent: {request.agent_id}")


class _FlowSubtaskRuntime:
    def __init__(self) -> None:
        self.execute_calls: list[str] = []
        self.validate_calls: list[str] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "flow-subtask-runtime",
            "version": 1,
        })

    def execute(self, request):
        self.execute_calls.append(request.task_id)
        return {
            "output": f"result:{request.task_id}",
            "role": request.assigned_role,
            "attempt": request.attempt,
        }

    def validate(self, request):
        self.validate_calls.append(request.task_id)
        return FlowSubtaskValidationResult(
            True,
            evidence_refs=(
                canonical_digest({
                    "fixture": "flow-validation",
                    "task_id": request.task_id,
                    "attempt": request.attempt,
                }),
            ),
        )


def _child_runtime():
    subtask_runtime = _FlowSubtaskRuntime()
    journal = InMemoryMachineJournal()
    registry = ChildResearchHostRegistry()
    registry.register_static(
        flow_subtask_host(journal=journal),
        FlowSubtaskBinding(subtask_runtime),
    )
    single = registry.executor()
    mechanics = ThreadPoolChildResearchBatchMechanics(
        single,
        max_workers=4,
    )
    return (
        BatchCapableRegisteredChildResearchMachineExecutor(
            single,
            mechanics,
        ),
        subtask_runtime,
        journal,
    )


def test_flow_aov_candidate_selection_rewards_parallel_modularity() -> None:
    candidates = (_chain(), _parallel(), _star(), _two_chains(), _diamond())
    selected, scores = flow_select_candidate(candidates)
    assert selected == 1
    assert scores[selected] == min(scores)
    assert flow_average_parallelism(_parallel()) == 4.0
    assert flow_average_parallelism(_chain()) == 1.0
    assert flow_dependency_complexity(_parallel()) == 0.0


def test_flow_method_runs_concurrent_ready_set_child_machines_and_lazy_refinement(
    tmp_path,
) -> None:
    agents = _FlowParentAgents()
    children, subtasks, journal = _child_runtime()
    result = run_method_program(
        FLOW_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            _context(),
            agent_loop=agents,
            child_machines=children,
        ),
        initial_state=flow_initial_state(
            task_id="paper-task",
            overall_task="Build the paper task with a modular AOV workflow.",
        ),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["task_success"] is True
    assert result.value["completed_task_ids"] == ("a", "b", "c", "d")
    assert result.value["incomplete_task_ids"] == ()
    assert result.value["refinement_count"] == 0
    assert result.value["task_execution_count"] == 4
    assert result.value["initial_candidate_selected_index"] == 1
    assert result.value["summary"] == "final synthesized output"
    assert agents.refinements == 0
    assert agents.calls.count("flow.workflow-initializer") == 5
    # Refinement is lazy: a fully successful ready-set execution never calls it.
    assert agents.calls.count("flow.workflow-refiner") == 0
    assert agents.calls.count("flow.summary") == 1
    assert sorted(subtasks.execute_calls) == ["a", "b", "c", "d"]
    assert sorted(subtasks.validate_calls) == ["a", "b", "c", "d"]
    assert result.value["ready_set_batches"][0]["ready_set"] == (
        "a",
        "b",
        "c",
        "d",
    )
    assert result.value["ready_set_batches"][0]["mode"] == "concurrent"
    assert len(
        result.value["ready_set_batches"][0]["mechanics_evidence_digests"]
    ) == 1
    assert len(result.value["ready_set_batches"][0]["child_machine_ids"]) == 4
    assert all(
        len(journal.commits(machine_id)) >= 3
        for machine_id in result.value["ready_set_batches"][0][
            "child_machine_ids"
        ]
    )


def test_flow_paper_native_study_binds_three_tasks_and_metrics() -> None:
    benchmark = build_flow_practical_task_set()
    assert benchmark.benchmark_id == FLOW_PRACTICAL_BENCHMARK_ID
    assert len(benchmark.selected_tasks(FLOW_PRACTICAL_SPLIT_ID)) == 3

    study = build_flow_iclr2025_study(benchmark)
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.benchmark_split_id == FLOW_PRACTICAL_SPLIT_ID
    assert study.trial_protocol_identity.protocol_id == (
        "flow.iclr2025.three-designed-tasks.v1"
    )
    assert {
        row.measurement_id for row in study.measurement_protocol.definitions
    } == {
        "task_success",
        "human_rating",
        "subtask_count",
        "refinement_count",
        "task_execution_count",
    }
    assert study.repetitions == 5
    assert study.seeds == (
        "paper-trial-1",
        "paper-trial-2",
        "paper-trial-3",
        "paper-trial-4",
        "paper-trial-5",
    )
