from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import WorkflowSurfaceBindingContext

from .context_action_operations import ContextActionTrialOperations


class ContextActionSurfaceFactory:
    surface_id = "context_action.operations.v1"
    reuse_scope = "run"

    @staticmethod
    def bind(context: WorkflowSurfaceBindingContext) -> ContextActionTrialOperations:
        return ContextActionTrialOperations(
            context.dispatcher,
            context.bound,
            context.participant_sessions,
            effect_intents=context.effect_intents,
        )


__all__ = ["ContextActionSurfaceFactory"]
