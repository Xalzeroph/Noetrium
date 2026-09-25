from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import JsonInput, JsonValue, freeze_json


class ResearchAction(StrEnum):
    RUN = "run"
    INSPECT = "inspect"
    STOP = "stop"
    RESUME = "resume"
    RECONCILE = "reconcile"
    EVIDENCE = "evidence"



@dataclass(frozen=True, slots=True)
class ResearchRequest:
    action: ResearchAction
    target: str
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ResearchAction):
            raise TypeError("research action must be ResearchAction")
        if not isinstance(self.target, str):
            raise TypeError("research target must be a string")
        target = self.target.strip()
        if not target:
            raise ValueError("research target must not be blank")
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class ResearchResult:
    action: ResearchAction
    target: str
    state: str
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ResearchAction):
            raise TypeError("research result action must be ResearchAction")
        if not isinstance(self.target, str) or not isinstance(self.state, str):
            raise TypeError("research result target/state must be strings")
        target = self.target.strip()
        state = self.state.strip()
        if not target or not state:
            raise ValueError("research result target/state must not be blank")
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "payload", freeze_json(self.payload))


class ResearchOperationFailure(RuntimeError):
    """Authoritative application result for an operation that did not complete safely."""

    def __init__(self, result: ResearchResult) -> None:
        if type(result) is not ResearchResult:
            raise TypeError("research operation failure requires ResearchResult")
        self.result = result
        super().__init__(f"research {result.action.value} entered {result.state}")


class ResearchApplicationPort(Protocol):
    """Application-owned authority behind the topology-hiding product facade."""

    def execute(self, request: ResearchRequest) -> ResearchResult: ...


class ResearchFacade:
    """Canonical Python facade; delegates every domain decision to an injected port."""

    def __init__(self, application: ResearchApplicationPort) -> None:
        if not callable(getattr(application, "execute", None)):
            raise TypeError("research application must implement execute(request)")
        self._application = application

    def _execute(
        self,
        action: ResearchAction,
        target: str,
        payload: JsonInput = None,
    ) -> ResearchResult:
        result = self._application.execute(ResearchRequest(action, target, payload))
        if not isinstance(result, ResearchResult):
            raise TypeError("research application returned a non-ResearchResult")
        if result.action is not action or result.target != target.strip():
            raise ValueError("research application result identity does not match request")
        return result

    def run(self, target: str, payload: JsonInput = None) -> ResearchResult:
        return self._execute(ResearchAction.RUN, target, payload)

    def inspect(self, target: str, payload: JsonInput = None) -> ResearchResult:
        return self._execute(ResearchAction.INSPECT, target, payload)

    def stop(self, target: str, payload: JsonInput = None) -> ResearchResult:
        return self._execute(ResearchAction.STOP, target, payload)

    def resume(self, target: str, payload: JsonInput = None) -> ResearchResult:
        return self._execute(ResearchAction.RESUME, target, payload)

    def reconcile(self, target: str, payload: JsonInput = None) -> ResearchResult:
        return self._execute(ResearchAction.RECONCILE, target, payload)

    def evidence(self, target: str, payload: JsonInput = None) -> ResearchResult:
        return self._execute(ResearchAction.EVIDENCE, target, payload)


__all__ = [
    "ResearchAction",
    "ResearchApplicationPort",
    "ResearchFacade",
    "ResearchOperationFailure",
    "ResearchRequest",
    "ResearchResult",
]
