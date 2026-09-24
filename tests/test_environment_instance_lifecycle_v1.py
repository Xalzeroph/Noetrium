from __future__ import annotations

from noetrium_platform.capabilities.environment.api import (
    EnvironmentCleanlinessKind,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentInstanceState,
    EnvironmentProfileGcAssessment,
    EnvironmentProfileReferenceSummary,
    ExecutionEnvironmentCatalogPort,
)


def test_environment_facade_exposes_instance_lifecycle_contracts() -> None:
    assert EnvironmentInstanceState.CLEAN.value == "clean"
    assert EnvironmentCleanlinessKind.OVERLAY_DESTROYED.value == "overlay_destroyed"
    assert EnvironmentInstance.__name__ == "EnvironmentInstance"
    assert EnvironmentCleanlinessProof.__name__ == "EnvironmentCleanlinessProof"
    assert EnvironmentProfileReferenceSummary.__name__ == "EnvironmentProfileReferenceSummary"
    assert EnvironmentProfileGcAssessment.__name__ == "EnvironmentProfileGcAssessment"
    assert ExecutionEnvironmentCatalogPort.__name__ == "ExecutionEnvironmentCatalogPort"
