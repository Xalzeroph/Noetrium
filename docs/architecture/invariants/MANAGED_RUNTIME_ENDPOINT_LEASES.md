# Managed runtime endpoint leases

Endpoint leases are runtime ownership records.

- Lease acquisition never changes semantic model-role binding.
- Expiry/replacement is recorded as runtime provenance.
- Effects must identify the concrete endpoint/replica used through receipts.
- Stale leases fail closed rather than silently routing elsewhere.
