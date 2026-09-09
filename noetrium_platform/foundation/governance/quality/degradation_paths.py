from __future__ import annotations

from pathlib import Path
import os
from typing import Iterator


_AUDIT_IMPLEMENTATION_FILES = {
    "noetrium_platform/foundation/governance/quality/degradation_contracts.py",
    "noetrium_platform/foundation/governance/quality/api/contracts.py",
    "noetrium_platform/foundation/governance/quality/degradation_paths.py",
    "noetrium_platform/foundation/governance/quality/degradation_python_scan.py",
    "noetrium_platform/foundation/governance/quality/degradation_config_scan.py",
    "noetrium_platform/foundation/governance/quality/no_degradation.py",
}


def is_excluded_path(rel: Path) -> bool:
    return (
        rel.as_posix() in _AUDIT_IMPLEMENTATION_FILES
        or any(
            part in {"tests", "__pycache__", "build", "dist", "node_modules", ".git", ".venv", "venv", ".local", ".pytest_cache", ".server-state"}
            or part.endswith(".egg-info")
            for part in rel.parts
        )
    )


def iter_audited_files(root: Path, *, suffixes: frozenset[str] | None = None) -> Iterator[Path]:
    """Yield deterministic non-excluded files without descending into ignored trees."""
    root = Path(root)
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)
        dirnames[:] = sorted(
            name for name in dirnames
            if not is_excluded_path(rel_dir / name)
        )
        for name in sorted(filenames):
            path = current_path / name
            rel = path.relative_to(root)
            if is_excluded_path(rel):
                continue
            if suffixes is not None and path.suffix.lower() not in suffixes:
                continue
            yield path


__all__ = ["is_excluded_path", "iter_audited_files"]
