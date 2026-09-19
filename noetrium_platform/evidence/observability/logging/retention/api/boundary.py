# vNext Boundary: observability/logging/retention

SYSTEM = "observability"
NODE = "observability/logging/retention"
OWNS = "retention, archival and deletion policy for logs"
MUST_NOT_OWN = "failure retention and artifact retention"
AUTHORITY = "log_retention"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="observability",
    node="observability/logging/retention",
    package_prefix='noetrium_platform.evidence.observability.logging.retention',
    authority_id="log_retention",
    owns="retention, archival and deletion policy for logs",
    must_not_own="failure retention and artifact retention",
    api_module='noetrium_platform.evidence.observability.logging.retention.api',
    runtime_module='noetrium_platform.evidence.observability.logging.retention.runtime',
    provider_module='noetrium_platform.evidence.observability.logging.retention.providers',
    composition_module='noetrium_platform.evidence.observability.logging.retention.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
