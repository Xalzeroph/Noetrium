from __future__ import annotations

from dataclasses import dataclass
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

@dataclass(frozen=True, slots=True)
class _ForensicProjectionWatermark:
    source_id: str
    position: int
    source_digest: str


class EventProjectionBuffer:
    """Owns only disposable event projection backlog and authoritative watermarks."""

    SOURCE_ID = "forensics.events"

    def __init__(self,index,*,batch_size:int)->None:
        if batch_size<=0:
            raise ValueError("event projection batch_size must be positive")
        self.index=index
        self.batch_size=batch_size
        self._items:list[
            tuple[NoetriumUnit,dict[str,object],_ForensicProjectionWatermark]
        ]=[]

    def add(
        self,
        event:NoetriumUnit,
        document:dict[str,object],
        rows:int,
        tail_hash:str,
    )->bool:
        self._items.append((
            event,
            document,
            _ForensicProjectionWatermark(self.SOURCE_ID,rows,tail_hash),
        ))
        return len(self._items)>=self.batch_size

    def current_cursor(self)->_ForensicProjectionWatermark|None:
        return None if not self._items else self._items[-1][2]

    def flush(self)->_ForensicProjectionWatermark|None:
        if not self._items:
            return None
        batch=tuple(self._items)
        cursor=batch[-1][2]
        self.index.project_events_batch(tuple(
            (event,document,item.position,item.source_digest)
            for event,document,item in batch
        ))
        self._items.clear()
        return cursor

    def backlog(self)->int:
        return len(self._items)
