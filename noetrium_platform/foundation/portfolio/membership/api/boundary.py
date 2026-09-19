# vNext Boundary: portfolio/membership

SYSTEM = "portfolio"
NODE = "portfolio/membership"
OWNS = "portfolio-level ownership and membership records"
MUST_NOT_OWN = "runtime participant sessions"
AUTHORITY = "portfolio_membership"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="portfolio",
    node="portfolio/membership",
    package_prefix='noetrium_platform.foundation.portfolio.membership',
    authority_id="portfolio_membership",
    owns="portfolio-level ownership and membership records",
    must_not_own="runtime participant sessions",
    api_module='noetrium_platform.foundation.portfolio.membership.api',
    runtime_module='noetrium_platform.foundation.portfolio.membership.runtime',
    provider_module='noetrium_platform.foundation.portfolio.membership.providers',
    composition_module='noetrium_platform.foundation.portfolio.membership.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
