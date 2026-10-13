"""Composition over frozen model deployment identities and endpoint routes."""

from .binding import FrozenDeploymentEndpointBinder, FrozenEndpointBinding
from .qualified import (
    build_adaptive_model_endpoint_pool,
    build_qualified_model_endpoint,
)
from .runtime_canary import build_runtime_canary_endpoint
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    QualifiedModelClosureReadError,
    PersistedQualifiedModelEndpointBinding,
    QualifiedModelDeploymentClosure,
    load_qualified_model_deployment_closure,
)

__all__ = [
    "FrozenDeploymentEndpointBinder",
    "FrozenEndpointBinding",
    "PersistedQualifiedModelEndpointBinding",
    "QualifiedModelClosureReadError",
    "QualifiedModelDeploymentClosure",
    "build_adaptive_model_endpoint_pool",
    "build_qualified_model_endpoint",
    "build_runtime_canary_endpoint",
    "load_qualified_model_deployment_closure",
]
