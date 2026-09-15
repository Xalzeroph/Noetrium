# Research reproductions

This directory contains method-owned fidelity assets for external agent research reproductions. It is not a second Platform runtime and it is not the canonical method inventory.

Canonical discovery scope: `research/catalog/agent_reproduction_scope.json`.  
Canonical reproduction/method inventory: `research/catalog/research_program.json`.

Each reproduction lane should pin the external paper/repository artifacts required for scientific fidelity, isolate method-owned semantics from Noetrium-owned runtime mechanisms, add focused scientific tests, and promote only genuinely reusable cross-method mechanisms into Platform systems.

A lane progresses through: discovered -> catalogued -> scaffolded -> pilot -> matched. `matched` requires benchmark/configuration/result evidence; implementing a control loop alone is never sufficient.

Reproductions must reuse Noetrium authorities for model invocation, capability/tool execution, environment lifecycle, checkpoints/recovery, evidence, observability and experiments. External repositories are research references, not runtime dependencies.
