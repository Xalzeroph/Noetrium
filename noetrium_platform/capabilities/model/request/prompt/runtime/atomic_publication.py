from __future__ import annotations
import os
from pathlib import Path
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from .publication_common import fsync_dir

def write_atomic_file(path:Path,data:bytes)->None:
    atomic_replace_bytes(path,data)

def publish_atomic_directory(tmp:Path,target:Path,parent:Path)->None:
    fsync_dir(tmp); os.replace(tmp,target); fsync_dir(parent)
