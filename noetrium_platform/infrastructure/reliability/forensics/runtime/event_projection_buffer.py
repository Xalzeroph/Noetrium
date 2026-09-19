from __future__ import annotations

from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.evidence.data.projection.api import ProjectionCursor


class EventProjectionBuffer:
    """Owns only disposable event projection backlog and authoritative watermarks."""

    SOURCE_ID = "forensics.events"

    def __init__(self,index,*,batch_size:int)->None:
        if batch_size<=0:
            raise ValueError("event projection batch_size must be positive")
        self.index=index
        self.batch_size=batch_size
        self._items:list[tuple[EventEnvelope,ProjectionCursor]]=[]

    def add(self,event:EventEnvelope,rows:int,tail_hash:str)->bool:
        self._items.append((event,ProjectionCursor(self.SOURCE_ID,rows,tail_hash)))
        return len(self._items)>=self.batch_size

    def current_cursor(self)->ProjectionCursor|None:
        return None if not self._items else self._items[-1][1]

    def flush(self)->ProjectionCursor|None:
        if not self._items:
            return None
        batch=tuple(self._items)
        cursor=batch[-1][1]
        self.index.project_events_batch(tuple((event,item.position,item.source_digest) for event,item in batch))
        self._items.clear()
        return cursor

    def backlog(self)->int:
        return len(self._items)
