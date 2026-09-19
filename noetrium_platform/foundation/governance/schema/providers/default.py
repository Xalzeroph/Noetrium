from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.leaf_contract import LeafHandler, SystemLeafProvider
from noetrium_platform.foundation.governance.schema.api.boundary import CONTRACT

PROVIDER = SystemLeafProvider(CONTRACT)

def provider() -> SystemLeafProvider:
    return PROVIDER

def bind(handler: LeafHandler, state_path=None):
    return PROVIDER.bind(handler, state_path)

__all__ = ["PROVIDER", "provider", "bind"]
