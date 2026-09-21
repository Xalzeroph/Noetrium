# Effect Identity Placement

Every externally observable capability/model/environment effect receives a stable effect identity scoped to one execution attempt. Effect identity is minted by the generic execution/effect boundary and recorded in Machine Journal receipts; paper Programs may reference effects but never mint competing identities. Replay resolves recorded effects by identity and exact replay must not silently create live effects.
