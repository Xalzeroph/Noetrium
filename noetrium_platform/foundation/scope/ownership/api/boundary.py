# vNext Boundary: scope/ownership

SYSTEM = "scope"
NODE = "scope/ownership"
OWNS = "generic owner links and owner-path rules"
MUST_NOT_OWN = "portfolio business metadata"
AUTHORITY = "scope_ownership"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="scope",
    node="scope/ownership",
    package_prefix='noetrium_platform.foundation.scope.ownership',
    authority_id="scope_ownership",
    owns="generic owner links and owner-path rules",
    must_not_own="portfolio business metadata",
    api_module='noetrium_platform.foundation.scope.ownership.api',
    runtime_module='noetrium_platform.foundation.scope.ownership.runtime',
    provider_module='noetrium_platform.foundation.scope.ownership.providers',
    composition_module='noetrium_platform.foundation.scope.ownership.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
