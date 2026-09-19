# vNext Boundary: platform/configuration

SYSTEM = "platform"
NODE = "platform/configuration"
OWNS = "platform configuration sources and frozen configuration snapshots"
MUST_NOT_OWN = "domain configuration semantics"
AUTHORITY = "platform_configuration"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="platform",
    node="platform/configuration",
    package_prefix='noetrium_platform.foundation.kernel.configuration',
    authority_id="platform_configuration",
    owns="platform configuration sources and frozen configuration snapshots",
    must_not_own="domain configuration semantics",
    api_module='noetrium_platform.foundation.kernel.configuration.api',
    runtime_module='noetrium_platform.foundation.kernel.configuration.runtime',
    provider_module='noetrium_platform.foundation.kernel.configuration.providers',
    composition_module='noetrium_platform.foundation.kernel.configuration.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
