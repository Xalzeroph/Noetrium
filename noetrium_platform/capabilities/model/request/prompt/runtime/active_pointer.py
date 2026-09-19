from __future__ import annotations

from pathlib import Path

from .atomic_publication import write_atomic_file
from .publication_common import fsync_dir


class ActivePromptPointer:
    """Single authority for the crash-safe ACTIVE generation pointer."""

    def __init__(self,path:Path)->None:
        self.path=path

    def read(self)->str|None:
        if not self.path.exists():
            return None
        value=self.path.read_text(encoding="utf-8").strip()
        return value or None

    def write(self,generation_id:str)->None:
        write_atomic_file(self.path,(generation_id+"\n").encode())
        fsync_dir(self.path.parent)
