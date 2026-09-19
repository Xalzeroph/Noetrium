from __future__ import annotations

from dataclasses import dataclass
import time

from .contracts import ServiceExitClass


@dataclass(frozen=True, slots=True)
class RestartHistory:
    timestamps: tuple[float,...] = ()


@dataclass(frozen=True, slots=True)
class RestartDecision:
    restart: bool
    reason: str
    history: RestartHistory


class ExactRestartPolicy:
    """Only a TEMPORARY exit may restart the same immutable service contract."""
    def __init__(self,*,max_restarts:int=6,window_s:float=900)->None:
        if max_restarts<0 or window_s<=0: raise ValueError("invalid restart policy")
        self.max_restarts=max_restarts; self.window_s=window_s
    def decide(self,exit_class:ServiceExitClass,history:RestartHistory,*,now:float|None=None)->RestartDecision:
        now=time.time() if now is None else now
        recent=tuple(x for x in history.timestamps if now-x<=self.window_s)
        if exit_class!=ServiceExitClass.TEMPORARY:
            return RestartDecision(False,f"exit class {exit_class.name} is terminal",RestartHistory(recent))
        if len(recent)>=self.max_restarts:
            return RestartDecision(False,"temporary restart rate limit exhausted",RestartHistory(recent))
        return RestartDecision(True,"exact same-contract temporary restart authorized",RestartHistory(recent+(now,)))
