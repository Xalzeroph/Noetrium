# vNext Boundary: operator/incident

SYSTEM = "operator"
NODE = "operator/incident"
OWNS = "incident triage and incident work surfaces"
MUST_NOT_OWN = "incident authority"
AUTHORITY = "operator_incident_view"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="operator",
    node="operator/incident",
    package_prefix='noetrium_platform.product.operator.incident',
    authority_id="operator_incident_view",
    owns="incident triage and incident work surfaces",
    must_not_own="incident authority",
    api_module='noetrium_platform.product.operator.incident.api',
    runtime_module='noetrium_platform.product.operator.incident.runtime',
    provider_module='noetrium_platform.product.operator.incident.providers',
    composition_module='noetrium_platform.product.operator.incident.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
