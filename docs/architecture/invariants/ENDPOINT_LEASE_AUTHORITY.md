# Endpoint lease authority

Endpoint leases are capability-resource ownership records. They prevent conflicting allocations and bind an endpoint to deployment generation and scope, but they do not identify a scientific model role or trial.

Lease acquisition and release belong to the resource/lifecycle plane. Downstream methods consume a resolved model capability and never allocate ports or endpoints themselves.
