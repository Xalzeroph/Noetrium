from __future__ import annotations

import os
from pathlib import Path


class CaptureFD:
    """Owns exactly one active append fd."""

    def __init__(self,path:Path)->None:
        self.path=path
        self.fd:int|None=None

    def open(self)->None:
        if self.fd is None:
            flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
            if os.name == "nt":
                flags |= getattr(os, "O_BINARY", 0)
            self.fd=os.open(self.path,flags,0o644)

    def write_all(self,view:memoryview)->None:
        if self.fd is None:
            raise RuntimeError("capture fd is not open")
        pos=0
        while pos<len(view):
            n=os.write(self.fd,view[pos:])
            if n<=0:
                raise OSError("capture write returned zero bytes")
            pos+=n

    def sync(self)->None:
        if self.fd is None:
            raise RuntimeError("capture fd is not open")
        os.fsync(self.fd)

    def close(self,*,sync:bool)->None:
        if self.fd is None:
            return
        if sync:
            os.fsync(self.fd)
        os.close(self.fd)
        self.fd=None
