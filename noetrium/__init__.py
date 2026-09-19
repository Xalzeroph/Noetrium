"""Noetrium: public package root.

Import contract families from noetrium.contracts and reusable reference
implementations from components. The root stays inert so importing
the distribution never constructs a registry, runtime, provider, or process.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("noetrium")
except PackageNotFoundError:
    __version__ = "0+local"

__all__ = ["__version__"]
