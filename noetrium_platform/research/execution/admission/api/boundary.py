# vNext Boundary: execution/admission

SYSTEM = "execution"
NODE = "execution/admission"
OWNS = "hierarchical execution quotas, identity-aware admission decisions and lease accounting"
MUST_NOT_OWN = "scheduling order/fairness, executor lifecycle or model/environment truth"
# Legacy leaf metadata projected from the topology catalog. This identifier does
# not grant an independent durable authority; direct authority is determined by
# the registry node_kind/canonical_authority classification.
AUTHORITY = "admission_decision"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="execution",
    node="execution/admission",
    package_prefix='noetrium_platform.research.execution.admission',
    authority_id="admission_decision",
    owns="hierarchical execution quotas, identity-aware admission decisions and lease accounting",
    must_not_own="scheduling order/fairness, executor lifecycle or model/environment truth",
    api_module='noetrium_platform.research.execution.admission.api',
    runtime_module='noetrium_platform.research.execution.admission.runtime',
    provider_module='noetrium_platform.research.execution.admission.providers',
    composition_module='noetrium_platform.research.execution.admission.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
