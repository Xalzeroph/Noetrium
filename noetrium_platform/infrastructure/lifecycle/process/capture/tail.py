from __future__ import annotations

import hashlib


class BoundedTail:
    """Owns the in-memory hot tail only."""

    def __init__(self,limit:int,initial:bytes=b"")->None:
        if limit<=0:
            raise ValueError("tail limit must be positive")
        self.limit=limit
        self._data=bytearray(initial[-limit:])

    def update(self,chunk:memoryview)->None:
        if len(chunk)>=self.limit:
            self._data=bytearray(chunk[-self.limit:])
            return
        self._data.extend(chunk)
        if len(self._data)>self.limit:
            del self._data[:-self.limit]

    def read(self,length:int|None=None)->bytes:
        length=self.limit if length is None else length
        if length<0 or length>self.limit:
            raise ValueError("tail length outside configured bounded tail")
        return bytes(self._data[-length:]) if length else b""

    def sha256(self)->str:
        return hashlib.sha256(bytes(self._data)).hexdigest()
