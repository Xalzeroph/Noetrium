# vNext Boundary: experimentation/variant

SYSTEM = "experimentation"
NODE = "experimentation/variant"
OWNS = "experiment variants, assignments and comparison semantics"
MUST_NOT_OWN = "model deployment internals"
AUTHORITY = "variant_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="experimentation",
    node="experimentation/variant",
    package_prefix='noetrium_platform.research.experimentation.variant',
    authority_id="variant_state",
    owns="experiment variants, assignments and comparison semantics",
    must_not_own="model deployment internals",
    api_module='noetrium_platform.research.experimentation.variant.api',
    runtime_module='noetrium_platform.research.experimentation.variant.runtime',
    provider_module='noetrium_platform.research.experimentation.variant.providers',
    composition_module='noetrium_platform.research.experimentation.variant.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
