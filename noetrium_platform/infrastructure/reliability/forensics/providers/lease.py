from __future__ import annotations
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
    InterprocessLockBusy,
)

class ForensicWriterBusy(RuntimeError): pass

class ForensicWriterLease:
    """Kernel-backed single-writer lease for authoritative forensic state and index activation."""
    def __init__(self,path:Path)->None: self.path=path; self._lock=InterprocessFileLock(path, blocking=False); self._acquired=False
    def acquire(self)->"ForensicWriterLease":
        try:
            self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise ForensicWriterBusy(f"forensic writer lease is held: {self.path}") from exc
        self._acquired=True; return self
    def release(self)->None:
        if not self._acquired: return
        self._lock.__exit__(None, None, None); self._acquired=False
    def __enter__(self): return self.acquire()
    def __exit__(self,*exc): self.release()
