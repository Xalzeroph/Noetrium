# vNext Boundary: platform/identity

SYSTEM = "platform"
NODE = "platform/identity"
OWNS = "platform identity and immutable platform metadata"
MUST_NOT_OWN = "workspace/project/run identity"
AUTHORITY = "platform_identity"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="platform",
    node="platform/identity",
    package_prefix='noetrium_platform.foundation.kernel.identity',
    authority_id="platform_identity",
    owns="platform identity and immutable platform metadata",
    must_not_own="workspace/project/run identity",
    api_module='noetrium_platform.foundation.kernel.identity.api',
    runtime_module='noetrium_platform.foundation.kernel.identity.runtime',
    provider_module='noetrium_platform.foundation.kernel.identity.providers',
    composition_module='noetrium_platform.foundation.kernel.identity.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
