from __future__ import annotations

"""Executable runtime owner for environment/instance/readiness."""

from noetrium_platform.foundation.kernel.kernel.leaf_contract import (
    BoundSystemLeafRuntime, LeafHandler, SystemLeafRuntimeOwner,
)
from noetrium_platform.capabilities.environment.instance.readiness.api.boundary import CONTRACT

OWNER = SystemLeafRuntimeOwner(CONTRACT)

def owner() -> SystemLeafRuntimeOwner:
    return OWNER

def runtime(handler: LeafHandler, state_path=None) -> BoundSystemLeafRuntime:
    """Bind domain behavior; no handler means no execution is permitted."""
    return OWNER.bind(handler, state_path)

__all__ = ["OWNER", "owner", "runtime"]
