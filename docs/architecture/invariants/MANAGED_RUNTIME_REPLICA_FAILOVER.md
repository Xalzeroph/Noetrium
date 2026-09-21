# Managed runtime replica failover

Replica failover is deployment behavior.

- Failover cannot alter frozen semantic model-role binding.
- Replica endpoint identity is runtime provenance, not treatment identity.
- Failed attempts remain journal-linked; replacement execution gets a distinct attempt identity.
- Provider substitution outside the frozen binding policy fails closed.
