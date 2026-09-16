from research.reproductions.hugginggpt import (
    HUGGINGGPT_FIDELITY,
    HuggingGPTStage,
    build_hugginggpt_task,
    hugginggpt_ready_task_ids,
    unfold_hugginggpt_generated_arguments,
)


def test_hugginggpt_fidelity_preserves_four_stage_controller_executor_workflow() -> None:
    fidelity = HUGGINGGPT_FIDELITY
    assert fidelity.paper_arxiv == "2303.17580"
    assert fidelity.stages == (
        HuggingGPTStage.TASK_PLANNING,
        HuggingGPTStage.MODEL_SELECTION,
        HuggingGPTStage.TASK_EXECUTION,
        HuggingGPTStage.RESPONSE_GENERATION,
    )
    assert fidelity.dependency_marker == "<GENERATED>"
    assert fidelity.ready_tasks_execute_concurrently is True
    assert fidelity.response_aggregation_order == "task_id"


def test_hugginggpt_generated_references_form_explicit_task_dependencies() -> None:
    task = build_hugginggpt_task(
        task_id=3,
        task="caption generated image",
        args={
            "image": "<GENERATED>-1",
            "mask": "<GENERATED>-2",
            "prompt": "describe it",
        },
    )
    assert task.dependencies == (1, 2)
    assert hugginggpt_ready_task_ids((task,), (1,)) == ()
    assert hugginggpt_ready_task_ids((task,), (1, 2)) == (3,)


def test_hugginggpt_unfolds_multi_resource_argument_into_branch_tasks() -> None:
    task = build_hugginggpt_task(
        task_id=5,
        task="process images",
        args={"image": "<GENERATED>-1,<GENERATED>-4", "prompt": "enhance"},
    )
    rows = unfold_hugginggpt_generated_arguments(task)

    assert len(rows) == 2
    assert [row.args_map["image"] for row in rows] == ["<GENERATED>-1", "<GENERATED>-4"]
    assert [row.dependencies for row in rows] == [(1,), (4,)]


def test_hugginggpt_root_tasks_are_immediately_ready_and_sorted_by_task_id() -> None:
    tasks = (
        build_hugginggpt_task(task_id=4, task="second", args={"x": "literal"}),
        build_hugginggpt_task(task_id=1, task="first", args={"x": "literal"}),
    )
    assert hugginggpt_ready_task_ids(tasks, ()) == (1, 4)
