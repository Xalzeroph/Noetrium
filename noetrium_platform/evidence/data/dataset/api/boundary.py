# vNext Boundary: data/dataset

SYSTEM = "data"
NODE = "data/dataset"
OWNS = "dataset identity, schema references and lifecycle"
MUST_NOT_OWN = "dataset physical storage implementation"
AUTHORITY = "dataset_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
