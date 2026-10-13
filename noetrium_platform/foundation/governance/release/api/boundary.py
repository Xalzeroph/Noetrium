# vNext Boundary: governance/release

SYSTEM = "governance"
NODE = "governance/release"
OWNS = "release identities, manifests, verification and promotion semantics"
MUST_NOT_OWN = "runtime process state"
AUTHORITY = "release_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
