from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import durable_replace_file, durable_unlink
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort

from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog import HashChainedJSONL
from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_hashlog import SegmentedHashChainedJSONL
from noetrium_platform.infrastructure.reliability.forensics.providers.index import ForensicIndex
from noetrium_platform.infrastructure.reliability.forensics.providers.lease import ForensicWriterLease

@dataclass(frozen=True, slots=True)
class IndexFreshnessReport:
    fresh: bool
    authoritative: dict[str,tuple[int,str]]
    indexed: dict[str,tuple[int,str]]

@dataclass(frozen=True, slots=True)
class IndexRebuildReport:
    objects: int
    state_writers: int
    authoritative: dict[str,tuple[int,str]]


def _verify_authoritative(root:Path)->dict[str,tuple[int,str]]:
    if not root.exists(): raise FileNotFoundError(root)
    return {
        "failures":HashChainedJSONL(root/"failures.chain.jsonl",read_only=True).verify(),
        "events":SegmentedHashChainedJSONL(root/"events.chain",read_only=True).verify(),
        "mutations":HashChainedJSONL(root/"mutations.chain.jsonl",read_only=True).verify(),
    }

def inspect_index_freshness(root:Path)->IndexFreshnessReport:
    authoritative=_verify_authoritative(root); path=root/"index.sqlite3"
    indexed=ForensicIndex(path,read_only=True).freshness() if path.exists() else {}
    return IndexFreshnessReport(authoritative==indexed,authoritative,indexed)

def _hash_payloads(path:Path):
    if not path.exists(): return
    with path.open("r",encoding="utf-8") as fh:
        for line in fh:
            if line.strip(): yield json.loads(line)["payload"]

def _event_payloads(root:Path):
    if not root.exists(): return
    for path in sorted(root.glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].jsonl")):
        yield from _hash_payloads(path)

def rebuild_forensic_index(root:Path, *, task_group: TaskGroupPort)->IndexRebuildReport:
    """Explicit maintenance transaction. Requires exclusive writer lease; authoritative ledgers are read-only."""
    lease=ForensicWriterLease(root/".writer.lock").acquire()
    try:
        before=_verify_authoritative(root); tmp=root/"index.rebuild.sqlite3"
        for suffix in ("","-wal","-shm"):
            p=Path(str(tmp)+suffix)
            if p.exists(): durable_unlink(p)
        actor=task_group.open_serial_actor(
            "forensics-index-rebuild",
            lane_id="forensics-index-rebuild-writer",
        )
        idx=ForensicIndex(tmp,writer_actor=actor); objects=0; writers=0
        for kind,items in (("failure",_hash_payloads(root/"failures.chain.jsonl")),("event",_event_payloads(root/"events.chain")),("mutation",_hash_payloads(root/"mutations.chain.jsonl"))):
            for payload in items:
                idx.add_raw_payload(kind,payload); objects+=1; writers+=int(kind=="mutation")
        for name,(rows,tail) in before.items(): idx.set_freshness(name,rows,tail)
        idx.close()
        after=_verify_authoritative(root)
        if before!=after: raise RuntimeError("authoritative ledgers changed during index rebuild")
        target=root/"index.sqlite3"
        for suffix in ("-wal","-shm"):
            side=Path(str(target)+suffix)
            if side.exists(): durable_unlink(side)
        durable_replace_file(tmp, target)
        return IndexRebuildReport(objects,writers,before)
    finally: lease.release()
