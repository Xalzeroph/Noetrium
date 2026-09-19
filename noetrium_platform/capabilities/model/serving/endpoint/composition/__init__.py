"""Composition over frozen model deployment identities and endpoint routes."""

from .binding import FrozenDeploymentEndpointBinder, FrozenEndpointBinding
from .qualified import build_openai_compatible_qualified_endpoint
from .runtime_canary import build_openai_compatible_runtime_canary_endpoint
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
    "build_openai_compatible_qualified_endpoint",
    "build_openai_compatible_runtime_canary_endpoint",
    "load_qualified_model_deployment_closure",
]
