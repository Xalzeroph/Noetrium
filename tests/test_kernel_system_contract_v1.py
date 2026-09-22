from noetrium_platform.foundation.kernel.kernel import (
    SystemIdentity,
    SystemPort,
    SystemService,
    SystemSpec,
)
import noetrium_platform.capabilities.environment.api as environment_api
import noetrium_platform.evidence.artifact.api as artifact_api
import noetrium_platform.infrastructure.lifecycle.api as lifecycle_api


def test_kernel_system_contract_has_one_public_owner() -> None:
    for module in (environment_api, artifact_api, lifecycle_api):
        for name in ("SystemIdentity", "SystemPort", "SystemSpec"):
            assert name not in getattr(module, "__all__", ())
            assert not hasattr(module, name) or getattr(module, name) is not SystemIdentity


def test_shared_system_service_is_a_read_only_kernel_boundary() -> None:
    spec = SystemSpec(
        identity=SystemIdentity("demo"),
        purpose="demo boundary",
        children=("child",),
        authorities=("demo_owner",),
    )
    service = SystemService(spec)
    assert isinstance(service, SystemPort)
    assert service.spec is spec
