# Study Authoring Boundary

`Study` and `AgentStudySpec` are paper-facing declarations. They may name scientific identities, benchmark scope, participants, model responsibilities, measurements, trial protocol, factors, repetitions, seeds, and scientific limits. They must not require provider endpoints, deployment topology, session handles, journal storage, evidence storage, or runtime proof objects.

The compiler lowers these declarations into canonical typed research protocol objects. Any repeated downstream translation from paper concepts into provider/runtime plumbing is platform debt and should be absorbed behind this boundary without expanding the kernel with paper-private concepts.
