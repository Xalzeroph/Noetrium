# Model replica sharding authority

Replica sharding is a deterministic execution projection over canonical experiment batches and frozen model bindings. It may optimize placement by capacity and cost, but cannot change assignment membership, batch identity, treatment identity, trial identity, or measurement semantics.

Worker and placement digests must bind all operational inputs needed to reproduce placement decisions while remaining outside scientific treatment identity.
