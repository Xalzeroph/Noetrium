from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.kernel.record_plane import event_from_document
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.failure.api import (
    failure_field,
    failure_from_dict,
    is_failure_record,
)
from noetrium_platform.infrastructure.reliability.forensics.api.runtime_parts import ForensicRuntimeParts
from noetrium_platform.infrastructure.reliability.forensics.api.mutation import (
    is_mutation_event,
    mutation_document,
)
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

    def append_failure(self,failure:NoetriumUnit)->str:
        self.require_write()
        assert self.event_lane is not None and self.failure_lane is not None
        def critical_append() -> str:
            # The causal Event journal is the occurrence truth. The failure
            # chain/index are rebuildable projections of the same Unit.
            self.event_lane._append_owned(failure)
            self.event_lane._flush_owned()
            return self.failure_lane.append_owned(failure)

        return self.event_lane.critical_call(critical_append)

    def append_failure_once(self,failure:NoetriumUnit)->tuple[bool,str|None]:
        self.require_write()
        assert self.event_lane is not None and self.failure_lane is not None
        def critical_append() -> tuple[bool, str | None]:
            payload=self.failures.find_payload("failure_id",failure_field(failure, "failure_id"))
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
            self.event_lane._append_owned(failure)
            self.event_lane._flush_owned()
            return True,self.failure_lane.append_owned(failure)
        return self.event_lane.critical_call(critical_append)

    def append_mutation_event(self,mutation:NoetriumUnit)->str:
        self.require_write()
        if not is_mutation_event(mutation):
            raise TypeError("forensic mutation append requires state.mutation Event Unit")
        assert self.event_lane is not None and self.mutation_lane is not None

        def critical_append() -> str:
            # State transition truth is the causal Event. The mutation chain and
            # state-writer index are deterministic projections of that Unit.
            self.event_lane._append_owned(mutation)
            self.event_lane._flush_owned()
            return self.mutation_lane.append_owned(mutation)

        return self.event_lane.critical_call(critical_append)

    def verify_failure_projection_rebuild(self)->tuple[NoetriumUnit,...]:
        """Prove the failure chain is a projection of the causal Event journal."""

        event_payloads=self.events.verified_payloads_after(0).payloads
        event_failures:dict[str,NoetriumUnit]={}
        for payload in event_payloads:
            event=event_from_document(payload)
            if not is_failure_record(event):
                continue
            failure_id=str(failure_field(event,"failure_id"))
            previous=event_failures.get(failure_id)
            if previous is not None and previous!=event:
                raise RuntimeError(
                    "causal Event journal contains conflicting failure identity: "
                    + failure_id
                )
            event_failures[failure_id]=event

        failure_payloads=self.failures.verified_payloads_after(0).payloads
        projected:dict[str,NoetriumUnit]={}
        for payload in failure_payloads:
            failure=failure_from_dict(payload)
            failure_id=str(failure_field(failure,"failure_id"))
            previous=projected.get(failure_id)
            if previous is not None and previous!=failure:
                raise RuntimeError(
                    "failure projection contains conflicting identity: "
                    + failure_id
                )
            projected[failure_id]=failure

        if projected!=event_failures:
            missing=tuple(sorted(set(event_failures)-set(projected)))
            extra=tuple(sorted(set(projected)-set(event_failures)))
            divergent=tuple(sorted(
                key for key in set(projected)&set(event_failures)
                if projected[key]!=event_failures[key]
            ))
            raise RuntimeError(
                "failure projection diverged from causal Event journal: "
                f"missing={missing} extra={extra} divergent={divergent}"
            )
        return tuple(event_failures[key] for key in sorted(event_failures))

    def verify_mutation_projection_rebuild(self)->tuple[NoetriumUnit,...]:
        """Prove the mutation chain is a projection of causal state Events."""

        event_payloads=self.events.verified_payloads_after(0).payloads
        event_mutations:dict[str,NoetriumUnit]={}
        for payload in event_payloads:
            event=event_from_document(payload)
            if not is_mutation_event(event):
                continue
            document=mutation_document(event)
            mutation_id=str(document["mutation_id"])
            previous=event_mutations.get(mutation_id)
            if previous is not None and previous!=event:
                raise RuntimeError(
                    "causal Event journal contains conflicting mutation identity: "
                    + mutation_id
                )
            event_mutations[mutation_id]=event

        mutation_payloads=self.mutations.verified_payloads_after(0).payloads
        projected:dict[str,dict[str,object]]={}
        for payload in mutation_payloads:
            mutation_id=str(payload["mutation_id"])
            previous=projected.get(mutation_id)
            current=dict(payload)
            if previous is not None and previous!=current:
                raise RuntimeError(
                    "mutation projection contains conflicting identity: "
                    + mutation_id
                )
            projected[mutation_id]=current

        expected={
            key:mutation_document(event)
            for key,event in event_mutations.items()
        }
        if projected!=expected:
            missing=tuple(sorted(set(expected)-set(projected)))
            extra=tuple(sorted(set(projected)-set(expected)))
            divergent=tuple(sorted(
                key for key in set(projected)&set(expected)
                if projected[key]!=expected[key]
            ))
            raise RuntimeError(
                "mutation projection diverged from causal Event journal: "
                f"missing={missing} extra={extra} divergent={divergent}"
            )
        return tuple(event_mutations[key] for key in sorted(event_mutations))

    def verify_all(self)->dict[str,tuple[int,str]]:
        return {
            "failures":self.failures.verify(),
            "events":self.events.verify(),
            "mutations":self.mutations.verify(),
        }

    def close(self)->None:
        self.lifecycle.close(self.flush_projections)
