# Managed runtime remote effect receipts

Remote execution does not create a second truth authority.

- Every externally observable remote effect must return a typed effect receipt.
- Receipts are ingested into the owning run's Machine Journal before derived evidence is claimable.
- Worker-local logs are diagnostics, never scientific truth.
- Receipt identity is derived from canonical run/trial/attempt/effect identity, not worker placement.
- Reassignment and retry must preserve trial identity while creating a distinct attempt identity.
