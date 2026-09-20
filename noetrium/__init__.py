"""Noetrium public package root.

Downstream projects use the single noetrium.api surface. The package root stays
inert so importing the distribution never constructs a registry, runtime,
provider, or process.
"""
from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from types import ModuleType

try:
    __version__ = version("noetrium")
except PackageNotFoundError:
    __version__ = "0+local"


def __getattr__(name: str) -> ModuleType:
    if name != "api":
        raise AttributeError(name)
    module = import_module("noetrium.api")
    globals()["api"] = module
    return module


__all__ = ["api", "__version__"]
