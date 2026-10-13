# Research Execution Authority

Research execution owns durable workflow progress and the accepted operation lifecycle. It does not own external-effect certainty, physical resource truth, or governance topology.

## Accepted execution state

Scientific work progresses only through the canonical Machine execution path. Program interpreters may propose transitions; the Machine authority accepts durable state progression. A scheduler, worker pool, status cache, or orchestration helper cannot become a second execution history.

## Admission

Admission consumes exact execution identity and current resource facts. Quotas and fairness may decide when eligible work is admitted, but they do not change the scientific identity of that work.

## External effects

Effectful work is prepared before the physical effect. If execution is interrupted after an effect may have occurred, the operation remains uncertain until the effect authority supplies reconciliation evidence. Callers cannot choose a certainty enum to bypass reconciliation.

Effect-free interrupted work may use the bounded retry path when its contract proves that no external mutation was possible. Effectful interrupted work requires the canonical effect proof.

## Recovery

Recovery continues the same frozen execution identity and durable state. It may reuse work only when the relevant accepted cut, child execution, checkpoint, or effect evidence proves reuse is valid. Recovery tools coordinate existing authorities; they do not create another lifecycle ledger.
