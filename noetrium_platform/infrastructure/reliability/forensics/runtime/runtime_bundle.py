from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope, failure_from_dict
from noetrium_platform.infrastructure.reliability.forensics.api.runtime_parts import ForensicRuntimeParts
from noetrium_platform.infrastructure.reliability.forensics.runtime.runtime_lifecycle import ForensicRuntimeLifecycle
from noetrium_platform.infrastructure.reliability.forensics.runtime.write_lanes import ForensicProjectionError


@dataclass(slots=True)
class ForensicRuntimeBundle:
    """Runtime façade over resource parts + lifecycle authority."""

    root:Path
    read_only:bool
    parts:ForensicRuntimeParts
    lifecycle:ForensicRuntimeLifecycle


    @property
    def failures(self): return self.parts.failures
    @property
    def events(self): return self.parts.events
    @property
    def mutations(self): return self.parts.mutations
    @property
    def index(self): return self.parts.index
    @property
    def event_lane(self): return self.parts.event_lane
    @property
    def failure_lane(self): return self.parts.failure_lane
    @property
    def mutation_lane(self): return self.parts.mutation_lane
    @property
    def closed(self)->bool: return self.lifecycle.closed

    def require_write(self)->None:
        if self.read_only:
            raise PermissionError("read-only forensic store cannot mutate")
        if self.closed:
            raise RuntimeError("forensic runtime bundle is closed")

    def flush_projections(self)->None:
        self.require_write()
        assert self.event_lane is not None
        self.event_lane.flush()

    def projection_backlog(self)->int:
        self.require_write()
        assert self.event_lane is not None
        return self.event_lane.backlog()

    def append_failure_once(self,failure:FailureEnvelope)->tuple[bool,str|None]:
        self.require_write()
        assert self.event_lane is not None and self.failure_lane is not None
        def critical_append() -> tuple[bool, str | None]:
            payload=self.failures.find_payload("failure_id",failure.failure_id)
            if payload is not None:
                authoritative=failure_from_dict(payload)
                rows,tail=self.failures.cached_tail
                try:
                    self.index.project_failure(authoritative,rows=rows,tail_hash=tail)
                except Exception as exc:
                    raise ForensicProjectionError(
                        "failures", rows, tail, exc, new_record=False
                    ) from exc
                return False,None
            return True,self.failure_lane.append_owned(failure)
        return self.event_lane.critical_call(critical_append)

    def verify_all(self)->dict[str,tuple[int,str]]:
        return {
            "failures":self.failures.verify(),
            "events":self.events.verify(),
            "mutations":self.mutations.verify(),
        }

    def close(self)->None:
        self.lifecycle.close(self.flush_projections)
