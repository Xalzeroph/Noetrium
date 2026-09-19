from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import ZERO_HASH


@dataclass(frozen=True, slots=True)
class SegmentSummary:
    index:int
    rows:int
    bytes:int
    start_prev_hash:str
    end_hash:str
    filename:str


class SegmentManifestStore:
    """Owns only durable segmented-ledger manifest publication."""

    def __init__(self,path:Path)->None:
        self.path=path

    def write(self,summaries:tuple[SegmentSummary,...])->None:
        payload={
            "schema_version":1,
            "segments":[asdict(x) for x in summaries],
            "total_rows":sum(x.rows for x in summaries),
            "tail_hash":summaries[-1].end_hash if summaries else ZERO_HASH,
        }
        raw=json.dumps(payload,sort_keys=True,ensure_ascii=False,indent=2).encode()
        atomic_replace_bytes(self.path, raw)
