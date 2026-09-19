# vNext Boundary: scope/identity

SYSTEM = "scope"
NODE = "scope/identity"
OWNS = "stable scope identities and typed scope kinds"
MUST_NOT_OWN = "portfolio metadata"
AUTHORITY = "scope_identity"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="scope",
    node="scope/identity",
    package_prefix='noetrium_platform.foundation.scope.identity',
    authority_id="scope_identity",
    owns="stable scope identities and typed scope kinds",
    must_not_own="portfolio metadata",
    api_module='noetrium_platform.foundation.scope.identity.api',
    runtime_module='noetrium_platform.foundation.scope.identity.runtime',
    provider_module='noetrium_platform.foundation.scope.identity.providers',
    composition_module='noetrium_platform.foundation.scope.identity.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
