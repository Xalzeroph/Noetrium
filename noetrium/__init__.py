"""Noetrium public package root.

Downstream projects use the single noetrium.api surface. The package root stays
inert so importing the distribution never constructs a registry, runtime,
provider, or process.
"""

from importlib.metadata import PackageNotFoundError, version

from . import api as api

try:
    __version__ = version("noetrium")
except PackageNotFoundError:
    __version__ = "0+local"

__all__ = ["api", "__version__"]
