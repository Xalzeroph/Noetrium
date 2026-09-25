# Recovery Lease Invariants

Recovery ownership is a crash-sensitive execution fence.

- Owner and manifest identity are mandatory, and acquisition/expiry timestamps must be finite with expiry strictly later than acquisition.
- Recovery TTL and caller-supplied observation time must be finite. `NaN` or infinity cannot enter acquisition, renewal, ownership assertion, or execution-lock construction.
- The durable checksummed recovery document must decode into the same typed lease contract. Non-canonical numeric values are classified as `RecoveryLeaseIntegrityError` rather than leaking kernel encoding errors.
- An expired lease cannot be renewed. Reusing a human owner label does not authorize release of a lease for another manifest.
- The filesystem execution lock and durable lease are independent authorities composed together; neither is allowed to substitute for the other.
- Corrupt or uncertain recovery ownership fails closed. A new recovery execution must not proceed by treating missing/invalid lease evidence as proof that no owner exists.
