"""Deterministic operator-facade conformance workload, not a production domain backend."""

from .application import ReferenceResearchApplication, build_reference_application

__all__ = ["ReferenceResearchApplication", "build_reference_application"]
