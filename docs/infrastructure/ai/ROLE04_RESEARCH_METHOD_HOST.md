# ROLE04 Research Method Host

Noetrium exposes two complementary downstream method paths.

The component path uses reusable Agent/Participant/Model capabilities when a paper changes one mechanism. The whole-method path uses `ResearchMethodProgram[TaskT, InputT, ResultT]` when the paper owns the complete cognition/control graph.

`ResearchMethodProgram` is adapted through `ResearchMethodProgramAdapter` into the canonical `MethodProgram` ABI when it enters Universal Method Machine execution. This keeps ROLE04 typed and transport-neutral while preventing a second lifecycle or execution authority.

`ResearchMethodProgram` is a structural public contract in `noetrium_platform.capabilities.participant.method.api`. A downstream method does not subclass a Platform runtime class and does not register a paper algorithm name upstream.

Concrete `TaskT`, `InputT`, and `ResultT` remain project-typed. They are not converted to `Any`, `object`, a universal JSON payload, or text merely to satisfy the host contract.

Dependencies such as Model, Environment, Artifact, or project-local capability ports are constructor-injected by composition. The method contract performs no provider discovery and owns no ambient registry.

`MethodProgramIdentity` binds the exact `MethodIdentity` implementation with an optional canonical configuration SHA-256. Implementation and configuration therefore remain distinct scientific identity facets.

## Authority boundary

`ResearchMethodProgram.run(...)` executes the downstream scientific control graph only after an external Trial/Run boundary has already been established. It does not own Run lifecycle, assignment expansion, resource acquisition, effect reconciliation, checkpoint stores, evidence finalization, or scientific validity.

ROLE03 remains the Trial/Run orchestration owner. Its public adapter should bind a `ResearchMethodProgram` into the neutral Trial lifecycle and freeze the exact program identity in run provenance. ROLE04 does not import ROLE03 runtime or compiler internals.

The existing `MethodSession` contract remains the first-party memory/recall/task-completion archetype used by older Agent workloads. It is not the universal definition of a research method. Consumer migration may eventually narrow or remove that archetype after ROLE03 cutover, but no compatibility alias should redefine `ResearchMethodProgram` in terms of `recall()` or `task_completed()`.

Stateful method checkpoint/open/close/revision traits remain orthogonal. They must compose through existing Participant/checkpoint/revision authorities rather than grow into mandatory no-op methods on `ResearchMethodProgram`.

## Conformance evidence

`tests/test_typed_role04_research_method_host_v1.py` defines a project-only control graph with typed dataclass task/input/result values and an injected scoring port. It implements neither `recall()` nor `task_completed()` and still satisfies `ResearchMethodProgram` structurally.

The same suite rejects non-canonical configuration/runtime artifact digests and proves configuration identity changes the bound program digest without changing the implementation identity.

## Stateful method trait

`StatefulResearchMethodProgram` is an optional orthogonal trait, not a larger base class. It exposes only project-owned scientific-state bytes through `checkpoint_state()` and `restore_state()`. The trait owns no Run, checkpoint-store, session, binding, checksum, or recovery authority.

A host wraps those bytes in the canonical `ParticipantCheckpoint` envelope, which binds the frozen Participant runtime binding, component/session identity and payload checksum. Restore therefore remains fail-closed on incompatible Platform identity while the downstream paper retains ownership of its internal state schema/encoding.

## Canonical Participant identity projection

The host does not reconstruct method identity in Experimentation. ROLE04 projects both a `ParticipantRequirement` and a frozen `ParticipantRuntimeBinding` through `method_program_identity_for_requirement()` / `method_program_identity_for_runtime_binding()` into the same `MethodProgramIdentity`. `require_method_program_runtime_binding()` rejects implementation or configuration drift before the downstream control graph executes. Non-`method` Participant kinds cannot be coerced into this projection.

## Component-level counterpart

Whole-method escape does not replace the built-in Agent archetype. Component-level research can continue to use the public `noetrium_platform.capabilities.participant.agent` facade together with public `participant.agent.api` ports. The facade internally owns the runtime import; downstream paper code does not import `participant.agent.runtime`.

The conformance test `test_typed_role04_agent_component_extension_v1.py` replaces the Planner with a synthetic `PaperOnlyPlanner` whose name/algorithm is absent from Platform source, executes the public `AgentCognitionLoop`, and uses only public Agent/kernel imports. This proves a paper can change one reusable component without reimplementing the whole Agent or editing Platform source.

## Process neutrality

`ResearchMethodProgram` is transport-neutral. The conformance suite runs the same project-defined program locally and in a spawned process, reconstructs only project task/input/context values at the process boundary, and proves identical `MethodProgramIdentity` plus typed result semantics.

That test is evidence about the contract, not a new process provider. ROLE04 does not own subprocess, IPC, worker supervision, or remote lifecycle authority; production out-of-process hosting must consume the platform process/runtime authorities and preserve the same Method contract.
