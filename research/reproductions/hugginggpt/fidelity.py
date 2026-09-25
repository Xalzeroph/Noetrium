from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


HUGGINGGPT_REPOSITORY = "microsoft/JARVIS"
HUGGINGGPT_SOURCE_COMMIT = "2c19142b56663a54b2c85f8622b38f98c5b2580f"


class HuggingGPTStage(StrEnum):
    TASK_PLANNING = "task_planning"
    MODEL_SELECTION = "model_selection"
    TASK_EXECUTION = "task_execution"
    RESPONSE_GENERATION = "response_generation"


@dataclass(frozen=True, slots=True)
class HuggingGPTFidelity:
    repository: str = HUGGINGGPT_REPOSITORY
    source_commit: str = HUGGINGGPT_SOURCE_COMMIT
    paper_arxiv: str = "2303.17580"
    source_path: str = "server/awesome_chat.py"
    stages: tuple[HuggingGPTStage, ...] = (
        HuggingGPTStage.TASK_PLANNING,
        HuggingGPTStage.MODEL_SELECTION,
        HuggingGPTStage.TASK_EXECUTION,
        HuggingGPTStage.RESPONSE_GENERATION,
    )
    dependency_marker: str = "<GENERATED>"
    dependency_identity: str = "task_id"
    model_selection_basis: str = "task-scoped model metadata and availability"
    ready_tasks_execute_concurrently: bool = True
    response_aggregation_order: str = "task_id"
    controller_is_llm: bool = True
    expert_models_are_executors: bool = True

    def __post_init__(self) -> None:
        if len(self.source_commit) != 40:
            raise ValueError("HuggingGPT source commit must be a full git SHA")
        if self.stages != (
            HuggingGPTStage.TASK_PLANNING,
            HuggingGPTStage.MODEL_SELECTION,
            HuggingGPTStage.TASK_EXECUTION,
            HuggingGPTStage.RESPONSE_GENERATION,
        ):
            raise ValueError("HuggingGPT four-stage workflow drifted")
        if self.dependency_marker != "<GENERATED>" or self.dependency_identity != "task_id":
            raise ValueError("HuggingGPT dependency semantics drifted")
        if not self.ready_tasks_execute_concurrently or self.response_aggregation_order != "task_id":
            raise ValueError("HuggingGPT execution/aggregation semantics drifted")
        if not self.controller_is_llm or not self.expert_models_are_executors:
            raise ValueError("HuggingGPT controller/executor roles drifted")


HUGGINGGPT_FIDELITY = HuggingGPTFidelity()


__all__ = [
    "HUGGINGGPT_FIDELITY",
    "HUGGINGGPT_REPOSITORY",
    "HUGGINGGPT_SOURCE_COMMIT",
    "HuggingGPTFidelity",
    "HuggingGPTStage",
]
