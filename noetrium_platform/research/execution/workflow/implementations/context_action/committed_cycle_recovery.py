from __future__ import annotations

from dataclasses import replace

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from .completion_recovery import CommittedCycleRecovery
from .method_completion import MethodCompletionAdapter
from .safe_action import SafeEnvironmentActionExecutor


class CommittedCycleRecoveryCoordinator:
    """Closes a cycle only when Method authority proves task completion already committed.

    This recovery-only collaborator cannot call normal observe/ingest/recall/task_completed.
    It composes Method completion reconciliation with external-effect reconciliation and the
    action-journal terminal consumption step.
    """

    def __init__(
        self,
        completion: MethodCompletionAdapter,
        safe_actions: SafeEnvironmentActionExecutor,
    ) -> None:
        self._completion = completion
        self._safe_actions = safe_actions

    def recover(
        self,
        *,
        action_type: str,
        action_payload: object,
        context: ExecutionContext,
    ) -> CommittedCycleRecovery | None:
        inspection = self._safe_actions.preflight_action_slot(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
        )
        if inspection.nonterminal is None:
            return None
        committed = self._completion.reconcile(context)
        if committed is None or committed.receipt is None:
            return None
        execution = self._safe_actions.recover_committed_action(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
        )
        final_context = self._project_final_context(
            context,
            execution.result.observation.generation
            if execution.result.observation is not None else None,
            committed.receipt.method_generation,
        )
        rows: list[OperationResult[JsonValue]] = list(inspection.operation_results)
        rows.append(committed.operation)
        rows.extend(execution.operation_results)
        rows.extend(self._safe_actions.confirm_trial_commit(
            action_type=action_type,
            action_payload=action_payload,
            context=final_context,
            consumption=committed.consumption,
        ))
        return CommittedCycleRecovery(
            execution.result,
            committed.receipt,
            final_context,
            tuple(rows),
        )

    @staticmethod
    def _project_final_context(
        context: ExecutionContext,
        environment_generation: str | None,
        method_generation: str | None,
    ) -> ExecutionContext:
        projected = context
        if environment_generation is not None:
            projected = projected.with_generation("environment", environment_generation)
        if method_generation is not None:
            projected = projected.with_generation("method", method_generation)
        return projected


__all__ = ["CommittedCycleRecoveryCoordinator"]
