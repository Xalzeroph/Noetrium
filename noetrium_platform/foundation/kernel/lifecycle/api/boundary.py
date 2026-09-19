# vNext Boundary: platform/lifecycle

SYSTEM = "platform"
NODE = "platform/lifecycle"
OWNS = "platform startup/shutdown/readiness semantics"
MUST_NOT_OWN = "service/process lifecycle"
AUTHORITY = "platform_lifecycle"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="platform",
    node="platform/lifecycle",
    package_prefix='noetrium_platform.foundation.kernel.lifecycle',
    authority_id="platform_lifecycle",
    owns="platform startup/shutdown/readiness semantics",
    must_not_own="service/process lifecycle",
    api_module='noetrium_platform.foundation.kernel.lifecycle.api',
    runtime_module='noetrium_platform.foundation.kernel.lifecycle.runtime',
    provider_module='noetrium_platform.foundation.kernel.lifecycle.providers',
    composition_module='noetrium_platform.foundation.kernel.lifecycle.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
