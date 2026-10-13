"""One isolated model-endpoint test composition, not a production fallback."""
from __future__ import annotations

from noetrium_platform.capabilities.model.serving.endpoint.runtime import AdaptiveModelEndpointPool
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import UnifiedSchedulingAuthority


def make_test_model_endpoint_pool(*args, **kwargs) -> AdaptiveModelEndpointPool:
    kwargs.setdefault("scheduling_authority", UnifiedSchedulingAuthority())
    return AdaptiveModelEndpointPool(*args, **kwargs)
