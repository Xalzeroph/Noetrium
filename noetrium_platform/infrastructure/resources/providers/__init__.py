"""Concrete providers spanning the parent resource authority boundary."""

from .sqlite_endpoint import SQLiteEndpointAllocationStore
from .sqlite_lease import SQLiteResourceLeaseRegistry

__all__ = ["SQLiteEndpointAllocationStore", "SQLiteResourceLeaseRegistry"]
