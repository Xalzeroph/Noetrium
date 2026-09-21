# Model replica pool authority

Replica pools are deployment projections of a frozen model binding. Replica count, placement, endpoint and health are operational metadata; they must not redefine semantic model role, treatment identity, trial identity, prompt identity, or model artifact identity.

Scale-out and replacement preserve the frozen binding digest. A replica may serve an invocation only when its deployment generation and binding identity match the compiled run requirements.
