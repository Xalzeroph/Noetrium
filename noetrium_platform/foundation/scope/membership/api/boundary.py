# vNext Boundary: scope/membership

SYSTEM = "scope"
NODE = "scope/membership"
OWNS = "membership of entities in scopes"
MUST_NOT_OWN = "participant sessions"
AUTHORITY = "scope_membership"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="scope",
    node="scope/membership",
    package_prefix='noetrium_platform.foundation.scope.membership',
    authority_id="scope_membership",
    owns="membership of entities in scopes",
    must_not_own="participant sessions",
    api_module='noetrium_platform.foundation.scope.membership.api',
    runtime_module='noetrium_platform.foundation.scope.membership.runtime',
    provider_module='noetrium_platform.foundation.scope.membership.providers',
    composition_module='noetrium_platform.foundation.scope.membership.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
