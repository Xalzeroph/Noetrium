"""Composition of platform-owned service lifecycle modules."""

from .local_runtime import (
    LocalServiceRuntimeComposer,
    UnsupportedHostProcessBackend,
    compose_local_process_backend,
)
from .supervisor import build_service_supervisor

__all__ = [
    "LocalServiceRuntimeComposer",
    "UnsupportedHostProcessBackend",
    "compose_local_process_backend",
    "build_service_supervisor",
]
