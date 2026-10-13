"""Governance analysis namespaces.

The three analyzers keep distinct typed contracts but share one bounded-context
ownership and lifecycle.
"""

from ..algorithm import api as algorithm
from ..concurrency import api as concurrency
from ..performance import api as performance

__all__ = ["algorithm", "concurrency", "performance"]
