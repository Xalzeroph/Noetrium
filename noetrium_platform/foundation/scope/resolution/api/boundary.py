# vNext Boundary: scope/resolution

SYSTEM = "scope"
NODE = "scope/resolution"
OWNS = "resolve a scope reference to canonical scope path"
MUST_NOT_OWN = "domain-specific lookup semantics"
AUTHORITY = "scope_resolution"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="scope",
    node="scope/resolution",
    package_prefix='noetrium_platform.foundation.scope.resolution',
    authority_id="scope_resolution",
    owns="resolve a scope reference to canonical scope path",
    must_not_own="domain-specific lookup semantics",
    api_module='noetrium_platform.foundation.scope.resolution.api',
    runtime_module='noetrium_platform.foundation.scope.resolution.runtime',
    provider_module='noetrium_platform.foundation.scope.resolution.providers',
    composition_module='noetrium_platform.foundation.scope.resolution.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
