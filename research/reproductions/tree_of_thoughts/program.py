from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import TREE_OF_THOUGHTS_GAME24_FIDELITY, TREE_OF_THOUGHTS_REFERENCE_FIDELITY
from .search import TreeSearchFrontier, assign_duplicate_zero_values, greedy_select

_GENERATE_AGENT_ID = "tot.generate"
_EVALUATE_AGENT_ID = "tot.evaluate"


def _required_text(state: Mapping[str, JsonValue], key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Tree of Thoughts state requires text field: {key}")
    return value


def _required_int(state: Mapping[str, JsonValue], key: str) -> int:
    value = state.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f"Tree of Thoughts state requires non-negative integer field: {key}")
    return value


def _text_tuple(value: JsonValue, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
    ):
        raise TypeError(f"Tree of Thoughts {field} must be a non-empty sequence")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"Tree of Thoughts {field} must contain text")
    return tuple(value)


def _number_tuple(value: JsonValue, field: str) -> tuple[float, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
    ):
        raise TypeError(f"Tree of Thoughts {field} must be a non-empty sequence")
    rows: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise TypeError(f"Tree of Thoughts {field} must contain numeric values")
        rows.append(float(item))
    return tuple(rows)


def _tot_generate_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "problem": _required_text(request.state, "problem"),
        "depth": _required_int(request.state, "depth"),
        "frontier": _text_tuple(request.state.get("frontier"), "frontier"),
    }


def _tot_evaluate_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "problem": _required_text(request.state, "problem"),
        "depth": _required_int(request.state, "depth"),
        "candidate_texts": _text_tuple(
            request.state.get("candidate_texts"),
            "candidate_texts",
        ),
    }


def tot_game24_initial_state(*, problem: str) -> JsonObject:
    if not isinstance(problem, str) or not problem.strip():
        raise ValueError("Tree of Thoughts Game24 problem is required")
    return {
        "problem": problem.strip(),
        "depth": 0,
        "frontier": TREE_OF_THOUGHTS_REFERENCE_FIDELITY.initial_frontier,
        "candidate_texts": (),
        "candidate_scores": (),
    }


def _record_generation(request: MethodNodeRequest) -> MethodNodeResult:
    candidates = _text_tuple(request.previous_value, "generated candidates")
    return MethodNodeResult(
        value=candidates,
        state_update={"candidate_texts": candidates},
    )


def _select_frontier(request: MethodNodeRequest) -> MethodNodeResult:
    candidates = _text_tuple(request.state.get("candidate_texts"), "candidate_texts")
    values = _number_tuple(request.previous_value, "evaluated values")
    scored = assign_duplicate_zero_values(candidates, values)
    selected = greedy_select(scored, count=TREE_OF_THOUGHTS_GAME24_FIDELITY.n_select_sample)
    depth = _required_int(request.state, "depth") + 1
    frontier = TreeSearchFrontier(depth, tuple(row.text for row in selected))
    scores = tuple({"text": row.text, "value": row.value} for row in selected)
    return MethodNodeResult(
        value={"depth": depth, "frontier": frontier.candidates, "scores": scores},
        state_update={
            "depth": depth,
            "frontier": frontier.candidates,
            "candidate_scores": scores,
        },
    )


def _route_depth(request: MethodNodeRequest) -> MethodNodeResult:
    depth = _required_int(request.state, "depth")
    terminal = depth >= TREE_OF_THOUGHTS_GAME24_FIDELITY.search_steps
    return MethodNodeResult(
        value={"depth": depth, "terminal": terminal},
        next_node="return" if terminal else "generate",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    frontier = _text_tuple(request.state.get("frontier"), "frontier")
    return MethodNodeResult(
        value={
            "problem": _required_text(request.state, "problem"),
            "depth": _required_int(request.state, "depth"),
            "candidates": frontier,
            "best_candidate": frontier[0],
            "candidate_scores": request.state.get("candidate_scores", ()),
        }
    )


def build_tot_game24_method_program() -> MethodProgram:
    """Compile the released Game24 BFS control loop into the universal MethodProgram ABI.

    The two agent nodes deliberately expose generation and value evaluation as
    separate model-facing roles. Prompt construction and provider invocation stay
    behind the platform model/agent binding; frontier update and greedy selection
    remain method-owned pure computation.
    """

    configuration: JsonObject = {
        "source_repository": TREE_OF_THOUGHTS_REFERENCE_FIDELITY.source.repository,
        "source_commit": TREE_OF_THOUGHTS_REFERENCE_FIDELITY.source.commit,
        "source_artifacts": TREE_OF_THOUGHTS_REFERENCE_FIDELITY.source.artifacts,
        "backend": TREE_OF_THOUGHTS_GAME24_FIDELITY.backend,
        "temperature": TREE_OF_THOUGHTS_GAME24_FIDELITY.temperature,
        "generation_mode": TREE_OF_THOUGHTS_GAME24_FIDELITY.generation_mode,
        "evaluation_mode": TREE_OF_THOUGHTS_GAME24_FIDELITY.evaluation_mode,
        "selection_mode": TREE_OF_THOUGHTS_GAME24_FIDELITY.selection_mode,
        "n_generate_sample": TREE_OF_THOUGHTS_GAME24_FIDELITY.n_generate_sample,
        "n_evaluate_sample": TREE_OF_THOUGHTS_GAME24_FIDELITY.n_evaluate_sample,
        "n_select_sample": TREE_OF_THOUGHTS_GAME24_FIDELITY.n_select_sample,
        "search_steps": TREE_OF_THOUGHTS_GAME24_FIDELITY.search_steps,
        "value_prompt_cache": TREE_OF_THOUGHTS_REFERENCE_FIDELITY.value_prompt_cache,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="tree-of-thoughts-game24",
            implementation_version="official-8050e67d",
            abi_version="noetrium.method-machine.v1",
            schema_version="tree-of-thoughts.game24.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    visits = TREE_OF_THOUGHTS_GAME24_FIDELITY.search_steps
    builder = MethodProgramBuilder(identity, entrypoint="generate")
    builder.agent(
        "generate",
        "tot.game24.generate",
        _GENERATE_AGENT_ID,
        ("record_generation",),
        view_handler=_tot_generate_view,
        max_visits=visits,
    )
    builder.compute(
        "record_generation",
        "tot.game24.record-generation",
        _record_generation,
        ("evaluate",),
        max_visits=visits,
    )
    builder.agent(
        "evaluate",
        "tot.game24.evaluate",
        _EVALUATE_AGENT_ID,
        ("select",),
        view_handler=_tot_evaluate_view,
        max_visits=visits,
    )
    builder.compute(
        "select",
        "tot.game24.greedy-select",
        _select_frontier,
        ("route",),
        max_visits=visits,
    )
    builder.route(
        "route",
        "tot.game24.depth-route",
        _route_depth,
        ("generate", "return"),
        max_visits=visits,
    )
    builder.return_node("return", "tot.game24.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=("tot.search.frontier", "model.invocation"),
        metric_names=("task_success", "model_call_count"),
        artifact_kinds=("tot_search_trace",),
    )


TOT_GAME24_METHOD_PROGRAM = build_tot_game24_method_program()


__all__ = [
    "TOT_GAME24_METHOD_PROGRAM",
    "build_tot_game24_method_program",
    "tot_game24_initial_state",
]
