# vNext Boundary: execution/scheduling

SYSTEM = "execution"
NODE = "execution/scheduling"
OWNS = "priority, aging, fairness and deterministic scheduling order"
MUST_NOT_OWN = "live resource/admission state, quotas or executor lifecycle"
AUTHORITY = "schedule_intent"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="execution",
    node="execution/scheduling",
    package_prefix='noetrium_platform.research.execution.scheduling',
    authority_id="schedule_intent",
    owns="priority, aging, fairness and deterministic scheduling order",
    must_not_own="live resource/admission state, quotas or executor lifecycle",
    api_module='noetrium_platform.research.execution.scheduling.api',
    runtime_module='noetrium_platform.research.execution.scheduling.runtime',
    provider_module='noetrium_platform.research.execution.scheduling.providers',
    composition_module='noetrium_platform.research.execution.scheduling.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
