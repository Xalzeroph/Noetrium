from noetrium_platform.foundation.kernel.kernel import (
    SystemIdentity,
    SystemPort,
    SystemService,
    SystemSpec,
)
from noetrium_platform.capabilities.environment.api import (
    SystemIdentity as EnvironmentIdentity,
    SystemPort as EnvironmentPort,
    SystemSpec as EnvironmentSpec,
)
from noetrium_platform.capabilities.environment.runtime import (
    SystemService as EnvironmentService,
)
from noetrium_platform.evidence.artifact.api import (
    SystemIdentity as ArtifactIdentity,
    SystemPort as ArtifactPort,
    SystemSpec as ArtifactSpec,
)
from noetrium_platform.evidence.artifact.runtime import SystemService as ArtifactService
from noetrium_platform.infrastructure.lifecycle.api import (
    SystemIdentity as LifecycleIdentity,
    SystemPort as LifecyclePort,
    SystemSpec as LifecycleSpec,
)
from noetrium_platform.infrastructure.lifecycle.runtime import SystemService as LifecycleService


def test_framework_system_contracts_are_singletons_across_compatibility_boundaries():
    assert EnvironmentIdentity is SystemIdentity
    assert ArtifactIdentity is SystemIdentity
    assert LifecycleIdentity is SystemIdentity
    assert EnvironmentSpec is SystemSpec
    assert ArtifactSpec is SystemSpec
    assert LifecycleSpec is SystemSpec
    assert EnvironmentPort is SystemPort
    assert ArtifactPort is SystemPort
    assert LifecyclePort is SystemPort
    assert EnvironmentService is SystemService
    assert ArtifactService is SystemService
    assert LifecycleService is SystemService


def test_shared_system_service_is_a_read_only_downstream_boundary():
    spec = SystemSpec(
        identity=SystemIdentity("demo"),
        purpose="demo boundary",
        children=("child",),
        authorities=("demo_owner",),
    )
    service = SystemService(spec)
    assert isinstance(service, SystemPort)
    assert service.spec is spec
