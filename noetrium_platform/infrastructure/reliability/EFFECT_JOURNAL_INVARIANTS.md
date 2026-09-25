# External Effect Journal Invariants

The effect WAL is the authority for may-have-happened external mutations.

- `PREPARED` enters the uncertainty region; absence of a later receipt is never evidence of `NO_EFFECT`.
- `RESULT_RECORDED` and `RECONCILED` remain non-terminal until the effect is authoritatively resolved and, when required, consumed by the bound completion operation.
- `NOT_APPLIED` requires a request-bound `NO_EFFECT` receipt with `verification_required == false`. Verification-pending evidence cannot authorize retry.
- `CONSUMED` requires authoritative `EFFECT_CONFIRMED` or `EFFECT_REJECTED` evidence plus completion evidence; impossible terminal combinations are journal corruption.
- Durable WAL decoding validates the intent checksum, request identity, scope index columns, phase, effect digest, effect/request binding, and completion checksum as one record.
- Corrupted redundant SQLite index metadata is not trusted as domain truth when a row is materialized; mismatches raise `EffectJournalIntegrityError`.
- SQLite lock waits use a finite positive timeout.

A caller must reconcile any unresolved intent in the same run/lifetime before another mutation can be considered safe. Missing or corrupt journal evidence fails closed.

A process restart does not relax generation fencing. When an unresolved intent for source generation `N` is durably present, reopening the SQLite journal must preserve that exact request/source identity; generation `N+1` cannot replace the intent or publish a successor request digest into it. Reconciliation or another authoritative terminal transition must resolve the predecessor first.
