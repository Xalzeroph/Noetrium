# vNext Boundary: observability/diagnostic/snapshot

SYSTEM = "observability"
NODE = "observability/diagnostic/snapshot"
OWNS = "portable diagnostic snapshots assembled from existing authorities"
MUST_NOT_OWN = "new business truth"
AUTHORITY = "diagnostic_snapshot"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="observability",
    node="observability/diagnostic/snapshot",
    package_prefix='noetrium_platform.evidence.observability.diagnostic.snapshot',
    authority_id="diagnostic_snapshot",
    owns="portable diagnostic snapshots assembled from existing authorities",
    must_not_own="new business truth",
    api_module='noetrium_platform.evidence.observability.diagnostic.snapshot.api',
    runtime_module='noetrium_platform.evidence.observability.diagnostic.snapshot.runtime',
    provider_module='noetrium_platform.evidence.observability.diagnostic.snapshot.providers',
    composition_module='noetrium_platform.evidence.observability.diagnostic.snapshot.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
