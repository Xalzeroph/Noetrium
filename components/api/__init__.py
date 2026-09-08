"""Stable downstream API for reusable reference components.

The generated Noetrium component facade is the only supported downstream
entrypoint for these generic memory-graph contracts.  SEM supplies the
semantic policy; this module supplies the generic graph substrate.
"""

from ..reference.single_agent.memory import (
    MemoryEdgeRecord,
    MemoryGraphConflict,
    MemoryGraphIntegrityError,
    MemoryGraphLedgerEntry,
    MemoryGraphOperation,
    MemoryGraphPort,
    MemoryGraphSnapshot,
    MemoryGraphTransaction,
    MemoryNodeRecord,
    VersionedMemoryGraph,
)

__all__ = (
    "MemoryEdgeRecord",
    "MemoryGraphConflict",
    "MemoryGraphIntegrityError",
    "MemoryGraphLedgerEntry",
    "MemoryGraphOperation",
    "MemoryGraphPort",
    "MemoryGraphSnapshot",
    "MemoryGraphTransaction",
    "MemoryNodeRecord",
    "VersionedMemoryGraph",
)
