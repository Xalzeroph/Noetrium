from __future__ import annotations

from noetrium.platform import run_method_program
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from research.reproductions.tree_of_thoughts import (
    TOT_GAME24_METHOD_PROGRAM,
    TREE_OF_THOUGHTS_GAME24_FIDELITY,
    tot_game24_initial_state,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="tot-game24-run",
        trace_id="trace",
        span_id="span",
        study_id="tot-game24",
        task_id="game24:0900",
        decision_cycle_id="search",
        participant_generations=(),
    )


class _DeterministicToTAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, request):
        self.calls.append(request.agent_id)
        if request.agent_id == "tot.generate":
            frontier = request.state["frontier"]
            assert isinstance(frontier, tuple)
            prefix = frontier[0]
            assert isinstance(prefix, str)
            rows = tuple(f"{prefix}{index}" for index in range(5))
            return MethodAgentResult(value=(*rows, rows[0]))
        if request.agent_id == "tot.evaluate":
            candidates = request.state["candidate_texts"]
            assert isinstance(candidates, tuple)
            assert len(candidates) == 6
            # The final repeated candidate deliberately receives the same raw
            # value as the first; ToT method semantics must zero the duplicate.
            return MethodAgentResult(value=(1.0, 0.9, 0.8, 0.7, 0.6, 1.0))
        raise AssertionError(f"unexpected ToT agent id: {request.agent_id}")


def test_tot_game24_method_program_compiles_bfs_into_explicit_model_and_selection_nodes(tmp_path) -> None:
    agent = _DeterministicToTAgent()
    result = run_method_program(
        TOT_GAME24_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(execution=_context(), agent_loop=agent),
        initial_state=tot_game24_initial_state(problem="4 4 6 8"),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED, result.failure
    assert result.value["depth"] == TREE_OF_THOUGHTS_GAME24_FIDELITY.search_steps == 4
    assert result.value["best_candidate"] == "0000"
    assert result.value["candidates"] == ("0000", "0001", "0002", "0003", "0004")
    assert tuple(row["value"] for row in result.value["candidate_scores"]) == (1.0, 0.9, 0.8, 0.7, 0.6)

    assert agent.calls == ["tot.generate", "tot.evaluate"] * 4
    visits = dict(result.visit_counts)
    assert visits["generate"] == 4
    assert visits["evaluate"] == 4
    assert visits["select"] == 4
    assert visits["route"] == 4


def test_tot_game24_program_identity_uses_the_same_typed_budget_as_the_study() -> None:
    assert TREE_OF_THOUGHTS_GAME24_FIDELITY.n_evaluate_sample == 3
    assert TREE_OF_THOUGHTS_GAME24_FIDELITY.n_select_sample == 5
    assert TREE_OF_THOUGHTS_GAME24_FIDELITY.search_steps == 4
    assert TOT_GAME24_METHOD_PROGRAM.configuration["n_evaluate_sample"] == 3
    assert TOT_GAME24_METHOD_PROGRAM.configuration["n_select_sample"] == 5
    assert TOT_GAME24_METHOD_PROGRAM.configuration["search_steps"] == 4
