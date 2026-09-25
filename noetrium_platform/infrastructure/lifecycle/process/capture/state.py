from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.process.api import CaptureWriterState


class CaptureStateCell:
    """Single mutation authority for capture writer counters/phase."""

    def __init__(self,state:CaptureWriterState)->None:
        self._state=state

    @property
    def value(self)->CaptureWriterState:
        return self._state

    def rotated(self)->CaptureWriterState:
        s=self._state
        self._state=CaptureWriterState(s.index+1,s.total_bytes,0,False,0)
        return self._state

    def appended(self,n:int,*,synced:bool)->CaptureWriterState:
        s=self._state
        self._state=CaptureWriterState(
            s.index,
            s.total_bytes+n,
            0 if synced else s.since_sync+n,
            False,
            s.active_size+n,
        )
        return self._state

    def synced(self)->CaptureWriterState:
        s=self._state
        self._state=CaptureWriterState(s.index,s.total_bytes,0,False,s.active_size)
        return self._state

    def sealed(self,total_bytes:int)->CaptureWriterState:
        s=self._state
        self._state=CaptureWriterState(s.index,total_bytes,0,True,s.active_size)
        return self._state
