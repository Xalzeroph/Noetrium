from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.alfworld import (
    ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT,
    ALFWORLD_TASK_FAMILIES,
    AlfworldTaskRecord,
    build_alfworld_paper_eval_task_set,
)
from research.benchmarks.game24 import (
    GAME24_PAPER_TASK_COUNT,
    Game24TaskRecord,
    build_game24_paper_task_set,
)
from research.benchmarks.rap_blocksworld import (
    RAP_BLOCKSWORLD_STEP4_TASK_COUNT,
    RapBlocksworldTaskRecord,
    build_rap_blocksworld_step4_task_set,
)
from research.benchmarks.webshop import (
    LATS_WEBSHOP_TASK_COUNT,
    WebShopTaskRecord,
    build_lats_webshop_task_set,
)
from research.reproductions.lats_webshop.fidelity import LATS_WEBSHOP_FIDELITY
from research.reproductions.lats_webshop.study import build_lats_webshop_released_study
from research.reproductions.rap_reasoning.study import build_rap_blocksworld_released_study
from research.reproductions.react_alfworld.study import build_react_alfworld_released_study
from research.reproductions.reflexion_alfworld.study import build_reflexion_alfworld_study
from research.reproductions.tree_of_thoughts.study import build_tot_game24_released_study


def _digest(namespace: str, index: int) -> str:
    return canonical_digest({"namespace": namespace, "index": index})


def _alfworld_cut():
    records = tuple(
        AlfworldTaskRecord(
            gamefile=f"valid_unseen/{family}/task-{index:03d}/game.tw-pddl",
            family=family,
            content_digest=_digest("alfworld", index),
        )
        for index, family in (
            (index, ALFWORLD_TASK_FAMILIES[index % len(ALFWORLD_TASK_FAMILIES)])
            for index in range(ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT)
        )
    )
    return build_alfworld_paper_eval_task_set(records, source_digest=_digest("alfworld-source", 0))


def _game24_cut():
    return build_game24_paper_task_set(
        tuple(
            Game24TaskRecord(index, f"1 2 3 {index}", _digest("game24", index))
            for index in range(900, 1000)
        ),
        source_digest=_digest("game24-source", 0),
    )


def _rap_cut():
    return build_rap_blocksworld_step4_task_set(
        tuple(
            RapBlocksworldTaskRecord(
                f"gpt-plan-benchmark/generated_basic/instance-{index}.pddl",
                _digest("rap-blocksworld", index),
            )
            for index in range(RAP_BLOCKSWORLD_STEP4_TASK_COUNT)
        ),
        source_digest=_digest("rap-blocksworld-source", 0),
    )


def _webshop_cut():
    return build_lats_webshop_task_set(
        tuple(WebShopTaskRecord(index, _digest("webshop", index)) for index in range(50)),
        source_digest=_digest("webshop-source", 0),
    )


def test_parallel_lineage_benchmark_cuts_freeze_released_task_cardinality() -> None:
    assert len(_alfworld_cut().tasks) == ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT == 134
    assert len(_game24_cut().tasks) == GAME24_PAPER_TASK_COUNT == 100
    assert len(_rap_cut().tasks) == RAP_BLOCKSWORLD_STEP4_TASK_COUNT == 57
    assert len(_webshop_cut().tasks) == LATS_WEBSHOP_TASK_COUNT == 50


def test_react_and_reflexion_share_one_alfworld_cut_but_keep_distinct_trial_semantics() -> None:
    benchmark = _alfworld_cut()
    react = build_react_alfworld_released_study(benchmark)
    reflexion = build_reflexion_alfworld_study(benchmark)

    assert react.benchmark.cut_digest == reflexion.benchmark.cut_digest
    assert react.repetitions == reflexion.repetitions == 1
    assert react.execution_policy.trial_budget.max_steps == 49
    assert reflexion.execution_policy.trial_budget.max_turns == 10 * 49
    assert tuple(
        (row.role, row.requirement_id)
        for row in reflexion.binding_requirements.model_roles
    ) == (
        ("action", "model.reflexion.action"),
        ("reflection", "model.reflexion.reflection"),
    )
    assert react.trial_protocol_identity.digest() != reflexion.trial_protocol_identity.digest()


def test_tot_rap_and_lats_compile_search_budget_into_typed_study_identity() -> None:
    tot = build_tot_game24_released_study(_game24_cut())
    rap = build_rap_blocksworld_released_study(_rap_cut())
    lats = build_lats_webshop_released_study(_webshop_cut())

    assert tot.execution_policy.trial_budget.max_steps == 4
    assert rap.execution_policy.trial_budget.max_steps == 10
    assert lats.execution_policy.trial_budget.max_turns == 30
    assert tuple(row.method_id for row in tot.binding_requirements.participants) == ("tree-of-thoughts",)
    assert tuple(row.method_id for row in rap.binding_requirements.participants) == ("rap",)
    assert tuple(row.method_id for row in lats.binding_requirements.participants) == ("lats",)
    assert "evaluation.plan-validity" in rap.binding_requirements.participants[0].capability_requirement_ids
    assert "environment.branch-state" in lats.binding_requirements.participants[0].capability_requirement_ids
    assert tuple(
        (row.role, row.requirement_id)
        for row in lats.binding_requirements.model_roles
    ) == (
        ("action", "model.lats.agent"),
        ("reflection", "model.lats.reflection"),
        ("value", "model.lats.value"),
    )


def test_lats_fidelity_distinguishes_launcher_budget_from_function_default() -> None:
    assert LATS_WEBSHOP_FIDELITY.max_iterations == 30
    assert LATS_WEBSHOP_FIDELITY.implementation_default_iterations == 50
    assert LATS_WEBSHOP_FIDELITY.task_start_index == 0
    assert LATS_WEBSHOP_FIDELITY.task_end_index == 50
    assert LATS_WEBSHOP_FIDELITY.task_count == 50
    assert LATS_WEBSHOP_FIDELITY.reference_model == "gpt-3.5-turbo"
