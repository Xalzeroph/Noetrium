from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.leaf_contract import LeafHandler
from noetrium_platform.product.operator.query.search.providers.default import bind as bind_provider

def compose(handler: LeafHandler, state_path=None):
    """Compose one executable leaf runtime with explicit domain behavior."""
    return bind_provider(handler, state_path)

__all__ = ["compose"]
