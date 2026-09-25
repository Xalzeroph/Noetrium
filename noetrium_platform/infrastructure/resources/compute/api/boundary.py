# vNext Boundary: resource/compute

SYSTEM = "resource"
NODE = "resource/compute"
OWNS = "compute resource identity, capacities and provider facts"
MUST_NOT_OWN = "environment packaging"
AUTHORITY = "compute_inventory"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
