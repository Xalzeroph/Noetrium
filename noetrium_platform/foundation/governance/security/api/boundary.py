# vNext Boundary: governance/security

SYSTEM = "governance"
NODE = "governance/security"
OWNS = "security/redaction/classification policy"
MUST_NOT_OWN = "scientific method semantics"
AUTHORITY = "security_policy"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="governance",
    node="governance/security",
    package_prefix='noetrium_platform.foundation.governance.security',
    authority_id="security_policy",
    owns="security/redaction/classification policy",
    must_not_own="scientific method semantics",
    api_module='noetrium_platform.foundation.governance.security.api',
    runtime_module='noetrium_platform.foundation.governance.security.runtime',
    provider_module='noetrium_platform.foundation.governance.security.providers',
    composition_module='noetrium_platform.foundation.governance.security.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
