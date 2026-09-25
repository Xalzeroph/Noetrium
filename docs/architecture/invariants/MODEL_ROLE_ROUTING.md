# Model-role routing

Programs address semantic model roles, not replica IDs or endpoints. The compiler freezes role-to-model bindings; runtime routing may select any healthy replica satisfying that frozen binding.

Routing changes are operational and journaled as effect metadata. They cannot alter prompt/model-role semantics or create a new treatment identity.
