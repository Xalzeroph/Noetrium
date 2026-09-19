from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest

FLOW_LATER_OFFICIAL_COMMIT = "1bbfe1e699e6f35d5d422306c9a5bd637da84759"


@dataclass(frozen=True, slots=True)
class FlowFidelity:
    source_repository: str = "https://github.com/tmllab/2025_ICLR_FLOW"
    audited_commit: str = FLOW_LATER_OFFICIAL_COMMIT
    publication_venue: str = "ICLR 2025"
    workflow_graph: str = "activity_on_vertex_dag"
    task_fields: tuple[str, ...] = (
        "id",
        "objective",
        "agent_id",
        "next",
        "prev",
        "status",
        "history",
        "remaining_dependencies",
        "agent",
        "output_format",
    )
    candidate_graphs: int = 5
    refine_threshold: int = 3
    max_refine_iterations: int = 5
    max_validation_iterations: int = 5
    initial_candidate_selection: str = (
        "z_dependency_complexity_minus_z_average_parallelism"
    )
    ready_tasks_execute_concurrently: bool = True
    refinement_waits_for_active_tasks: bool = True
    refinement_is_lazy: bool = True
    validation_per_completed_subtask: bool = True
    failed_subtasks_can_reexecute_with_feedback: bool = True
    refinement_can_add_edit_or_reassign_tasks: bool = True
    final_summary_after_workflow: bool = True
    fidelity_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("Flow audited commit must be a full git SHA")
        if self.workflow_graph != "activity_on_vertex_dag":
            raise ValueError("Flow AOV workflow semantics drifted")
        if self.candidate_graphs != 5:
            raise ValueError("Flow audited executable candidate_graphs drifted")
        if self.refine_threshold != 3:
            raise ValueError("Flow audited executable refine_threshold drifted")
        if self.max_refine_iterations != 5:
            raise ValueError("Flow audited executable max_refine_iterations drifted")
        if self.max_validation_iterations != 5:
            raise ValueError("Flow audited executable max_validation_iterations drifted")
        if self.initial_candidate_selection != (
            "z_dependency_complexity_minus_z_average_parallelism"
        ):
            raise ValueError("Flow candidate selection semantics drifted")
        if not all((
            self.ready_tasks_execute_concurrently,
            self.refinement_waits_for_active_tasks,
            self.refinement_is_lazy,
            self.validation_per_completed_subtask,
            self.failed_subtasks_can_reexecute_with_feedback,
            self.refinement_can_add_edit_or_reassign_tasks,
            self.final_summary_after_workflow,
        )):
            raise ValueError("Flow runtime/refinement semantics drifted")
        object.__setattr__(
            self,
            "fidelity_digest",
            canonical_digest({
                "source_repository": self.source_repository,
                "audited_commit": self.audited_commit,
                "publication_venue": self.publication_venue,
                "workflow_graph": self.workflow_graph,
                "task_fields": self.task_fields,
                "candidate_graphs": self.candidate_graphs,
                "refine_threshold": self.refine_threshold,
                "max_refine_iterations": self.max_refine_iterations,
                "max_validation_iterations": self.max_validation_iterations,
                "initial_candidate_selection": self.initial_candidate_selection,
                "ready_tasks_execute_concurrently": (
                    self.ready_tasks_execute_concurrently
                ),
                "refinement_waits_for_active_tasks": (
                    self.refinement_waits_for_active_tasks
                ),
                "refinement_is_lazy": self.refinement_is_lazy,
                "validation_per_completed_subtask": (
                    self.validation_per_completed_subtask
                ),
                "failed_subtasks_can_reexecute_with_feedback": (
                    self.failed_subtasks_can_reexecute_with_feedback
                ),
                "refinement_can_add_edit_or_reassign_tasks": (
                    self.refinement_can_add_edit_or_reassign_tasks
                ),
                "final_summary_after_workflow": self.final_summary_after_workflow,
            }),
        )


FLOW_FIDELITY = FlowFidelity()

__all__ = [
    "FLOW_FIDELITY",
    "FLOW_LATER_OFFICIAL_COMMIT",
    "FlowFidelity",
]
