from __future__ import annotations

from .families import FAMILY_BUILDERS
from ..runtime.registry import MetricRegistry
from .extended_family import definitions as extended_definitions


def build_default_registry() -> MetricRegistry:
    registry = MetricRegistry()
    for build_family in FAMILY_BUILDERS:
        for definition in build_family():
            registry.register(definition)
    for definition in extended_definitions():
        registry.register(definition)
    return registry
