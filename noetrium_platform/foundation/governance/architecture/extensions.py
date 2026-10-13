from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType


_EXTENSION_NAMESPACES = ("projects",)
_EXTENSION_SUFFIX = "governance.architecture"


def discover_architecture_extensions(root: Path) -> tuple[ModuleType, ...]:
    """Discover repository-owned architecture extensions without naming concrete projects.

    An extension lives at ``<namespace>/<package>/governance/architecture/__init__.py``
    where namespace is currently ``projects``. The core platform owns
    discovery only; each concrete method/project owns its own scientific invariants.
    """

    root = Path(root).resolve()
    modules: list[ModuleType] = []
    for namespace in _EXTENSION_NAMESPACES:
        base = root / namespace
        if not base.is_dir():
            continue
        for package in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")):
            marker = package / "governance" / "architecture" / "__init__.py"
            if not marker.is_file():
                continue
            modules.append(importlib.import_module(f"{namespace}.{package.name}.{_EXTENSION_SUFFIX}"))
    return tuple(modules)


__all__ = ["discover_architecture_extensions"]
