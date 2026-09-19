from __future__ import annotations
from pathlib import Path

class ProjectRootNotFound(RuntimeError):
    pass

def discover_project_root(anchor: str | Path) -> Path:
    path=Path(anchor).resolve()
    current=path if path.is_dir() else path.parent
    for candidate in (current, *current.parents):
        if (candidate/'pyproject.toml').is_file() and (candidate/'noetrium_platform').is_dir():
            return candidate
    raise ProjectRootNotFound(f"cannot discover project root from {path}")

__all__=["ProjectRootNotFound","discover_project_root"]
