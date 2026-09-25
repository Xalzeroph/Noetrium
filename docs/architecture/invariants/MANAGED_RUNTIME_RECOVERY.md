# Managed runtime recovery

Infrastructure recovery is generic and journal-aware.

- Recovery never rewrites completed journal facts.
- Retry/restart creates infrastructure attempt provenance without changing trial identity.
- Paper-specific reflection/self-correction remains Program semantics.
- Recovery leases prevent duplicate concurrent ownership of the same recovery action.
