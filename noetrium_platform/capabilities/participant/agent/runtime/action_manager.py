from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from ..api.cognition import AgentActionStep, AgentStepReceipt
from ..api.cognition_ports import AgentActionExecutorPort


class ActionLifecycleState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class AgentActionManagerError(RuntimeError):
    def __init__(self, code: str, message: str, *, receipt: AgentStepReceipt | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.receipt = receipt


@dataclass(frozen=True, slots=True)
class ActionExecutionPolicy:
    timeout_s: float = 120.0
    retry_on_rejection: int = 0
    resumable: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not math.isfinite(float(self.timeout_s))
            or self.timeout_s <= 0
            or type(self.retry_on_rejection) is not int
            or self.retry_on_rejection < 0
        ):
            raise ValueError("action policy limits are invalid")


@dataclass(frozen=True, slots=True)
class ActionManagerSnapshot:
    schema_version: str
    state: ActionLifecycleState
    active_action_id: str
    active_sequence_id: str
    interrupt_reason: str
    completed_actions: int
    failed_actions: int

    def __post_init__(self) -> None:
        if self.schema_version != "agent-action-manager.v1":
            raise ValueError("unsupported action manager snapshot")
        if min(self.completed_actions, self.failed_actions) < 0:
            raise ValueError("action manager counters cannot be negative")


class AgentActionManager(AgentActionExecutorPort):
    """Serial action lifecycle with cooperative interruption and timeout proof.

    Provider actions may be asynchronous, while the platform executor is
    intentionally synchronous at the ABI boundary.  The manager therefore
    provides cooperative cancellation and measures the provider call.  A
    provider that needs hard cancellation must expose it behind its executor;
    this class never pretends that a timed-out external effect was reverted.
    """

    def __init__(self, executor: AgentActionExecutorPort, *, clock: Callable[[], float]) -> None:
        self._executor = executor
        self._clock = clock
        self._state = ActionLifecycleState.IDLE
        self._active_action_id = ""
        self._active_sequence_id = ""
        self._interrupt_reason = ""
        self._completed_actions = 0
        self._failed_actions = 0

    @property
    def state(self) -> ActionLifecycleState:
        return self._state

    @property
    def active_action_id(self) -> str:
        return self._active_action_id

    def request_interrupt(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("interrupt reason is required")
        self._interrupt_reason = reason.strip()
        if self._state is ActionLifecycleState.RUNNING:
            self._state = ActionLifecycleState.INTERRUPTED

    def clear_interrupt(self) -> None:
        self._interrupt_reason = ""
        if self._state is ActionLifecycleState.INTERRUPTED:
            self._state = ActionLifecycleState.IDLE

    def execute(
        self,
        step: AgentActionStep,
        context: ExecutionContext,
        *,
        policy: ActionExecutionPolicy | None = None,
    ) -> AgentStepReceipt:
        selected = policy or ActionExecutionPolicy(timeout_s=step.timeout_s)
        if self._state is ActionLifecycleState.RUNNING:
            raise AgentActionManagerError("ACTION_ALREADY_RUNNING", "another action is active")
        if self._interrupt_reason:
            raise AgentActionManagerError("ACTION_INTERRUPTED", self._interrupt_reason)
        self._state = ActionLifecycleState.RUNNING
        self._active_action_id = step.action_id
        self._active_sequence_id = step.sequence_id
        started = self._clock()
        attempts = 0
        try:
            while True:
                attempts += 1
                receipt = self._executor.execute(step, context)
                if not isinstance(receipt, AgentStepReceipt):
                    raise AgentActionManagerError("ACTION_INVALID_RECEIPT", "executor returned an invalid receipt")
                if receipt.action_id != step.action_id or receipt.sequence_id != step.sequence_id:
                    raise AgentActionManagerError("ACTION_IDENTITY_DRIFT", "executor receipt identity drift", receipt=receipt)
                elapsed = self._clock() - started
                if elapsed > selected.timeout_s:
                    self._state = ActionLifecycleState.TIMED_OUT
                    self._failed_actions += 1
                    raise AgentActionManagerError("ACTION_TIMEOUT", "action exceeded its bounded timeout", receipt=receipt)
                if receipt.accepted or attempts > selected.retry_on_rejection:
                    self._state = ActionLifecycleState.COMPLETED if receipt.accepted else ActionLifecycleState.FAILED
                    if receipt.accepted:
                        self._completed_actions += 1
                    else:
                        self._failed_actions += 1
                    return receipt
        except AgentActionManagerError:
            raise
        except BaseException as exc:
            self._state = ActionLifecycleState.FAILED
            self._failed_actions += 1
            raise AgentActionManagerError("ACTION_EXECUTION_FAILED", str(exc)) from exc
        finally:
            self._active_action_id = ""
            self._active_sequence_id = ""

    def snapshot(self) -> ActionManagerSnapshot:
        return ActionManagerSnapshot(
            schema_version="agent-action-manager.v1",
            state=self._state,
            active_action_id=self._active_action_id,
            active_sequence_id=self._active_sequence_id,
            interrupt_reason=self._interrupt_reason,
            completed_actions=self._completed_actions,
            failed_actions=self._failed_actions,
        )

    def restore(self, snapshot: ActionManagerSnapshot) -> None:
        if snapshot.state is ActionLifecycleState.RUNNING:
            raise ValueError("a running action cannot be restored as durable state")
        self._state = snapshot.state
        self._active_action_id = snapshot.active_action_id
        self._active_sequence_id = snapshot.active_sequence_id
        self._interrupt_reason = snapshot.interrupt_reason
        self._completed_actions = snapshot.completed_actions
        self._failed_actions = snapshot.failed_actions


__all__ = [
    "ActionExecutionPolicy",
    "ActionLifecycleState",
    "ActionManagerSnapshot",
    "AgentActionManager",
    "AgentActionManagerError",
]
