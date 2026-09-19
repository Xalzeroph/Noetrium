# vNext Boundary: observability/status/lifecycle_view

SYSTEM = "observability"
NODE = "observability/status/lifecycle_view"
OWNS = "read-only lifecycle status views"
MUST_NOT_OWN = "lifecycle state authority"
AUTHORITY = "lifecycle_projection"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="observability",
    node="observability/status/lifecycle_view",
    package_prefix='noetrium_platform.evidence.observability.status.lifecycle_view',
    authority_id="lifecycle_projection",
    owns="read-only lifecycle status views",
    must_not_own="lifecycle state authority",
    api_module='noetrium_platform.evidence.observability.status.lifecycle_view.api',
    runtime_module='noetrium_platform.evidence.observability.status.lifecycle_view.runtime',
    provider_module='noetrium_platform.evidence.observability.status.lifecycle_view.providers',
    composition_module='noetrium_platform.evidence.observability.status.lifecycle_view.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
