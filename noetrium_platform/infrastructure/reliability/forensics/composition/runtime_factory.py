from __future__ import annotations

from pathlib import Path
import hashlib

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort

from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog import HashChainedJSONL
from noetrium_platform.infrastructure.reliability.forensics.providers.index import ForensicIndex
from noetrium_platform.infrastructure.reliability.forensics.providers.lease import ForensicWriterLease
from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_hashlog import SegmentedHashChainedJSONL
from noetrium_platform.infrastructure.reliability.forensics.api.runtime_parts import ForensicRuntimeParts
from noetrium_platform.infrastructure.reliability.forensics.runtime.write_lanes import CriticalWriteLane, EventWriteLane


def build_forensic_runtime_parts(
    root:Path,
    *,
    read_only:bool,
    event_projection_batch:int,
    task_group:TaskGroupPort | None,
)->ForensicRuntimeParts:
    """Construct runtime resources; no freshness/read-barrier bootstrap happens here."""

    lease=None
    if read_only:
        if not root.exists():
            raise FileNotFoundError(root)
    else:
        root.mkdir(parents=True,exist_ok=True)
        lease=ForensicWriterLease(root/".writer.lock").acquire()

    failures = events = mutations = index = None
    try:
        failures=HashChainedJSONL(root/"failures.chain.jsonl",fsync_every=1,read_only=read_only)
        events=SegmentedHashChainedJSONL(
            root/"events.chain",
            max_segment_bytes=8*1024*1024,
            fsync_every=32,
            read_only=read_only,
        )
        mutations=HashChainedJSONL(root/"mutations.chain.jsonl",fsync_every=1,read_only=read_only)
        if read_only:
            if task_group is not None:
                raise ValueError("read-only forensic runtime cannot own a task group")
            index=ForensicIndex(root/"index.sqlite3",read_only=True,writer_actor=None)
            event_lane=None
            failure_lane=None
            mutation_lane=None
        else:
            if task_group is None:
                raise ValueError("writable forensic runtime requires task_group")
            identity=hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
            coordinator=task_group.open_serial_actor(
                f"forensics-ledger:{identity}",
                lane_id=f"forensics-ledger-writer:{identity}",
            )
            index_actor=task_group.open_serial_actor(
                f"forensics-index:{identity}",
                lane_id=f"forensics-index-writer:{identity}",
            )
            index=ForensicIndex(root/"index.sqlite3",read_only=False,writer_actor=index_actor)
            event_lane=EventWriteLane(
                events,index,batch_size=event_projection_batch,actor=coordinator
            )
            failure_lane=CriticalWriteLane(
                "failures",failures,lambda obj,**kw:index.project_failure(obj,**kw)
            )
            mutation_lane=CriticalWriteLane(
                "mutations",mutations,lambda obj,**kw:index.project_mutation(obj,**kw)
            )
        return ForensicRuntimeParts(
            failures,events,mutations,index,
            event_lane,failure_lane,mutation_lane,lease,
        )
    except Exception:
        # Roll back partially constructed resources in reverse dependency order.
        for resource in (index, mutations, events, failures):
            close=getattr(resource,"close",None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass
        if lease is not None:
            lease.release()
        raise


def bootstrap_projection_freshness(parts:ForensicRuntimeParts)->None:
    """Initialize only empty-ledger freshness markers for a writable runtime."""
    if parts.writer_lease is None:
        raise PermissionError("read-only forensic runtime cannot bootstrap projection freshness")
    existing=parts.index.freshness()
    for name,ledger in (
        ("failures",parts.failures),
        ("events",parts.events),
        ("mutations",parts.mutations),
    ):
        if name not in existing:
            count,tail=ledger.cached_tail
            if count==0:
                parts.index.set_freshness(name,count,tail)
