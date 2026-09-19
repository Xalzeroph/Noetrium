# Noetrium Component Layers

Noetrium is intentionally split into three dependency tiers:

1. noetrium_platform/ is the infrastructure and authority tier. It owns
   identity, bindings, execution, recovery, measurements, artifacts, evidence,
   and typed producer ports.
   The reusable memory component layer owns working, episodic, vector and
   versioned graph memory substrates; it does not own paper-specific semantics.
2. components/reference/single_agent/agent, components/reference/single_agent/memory, and components/reference/single_agent/tools are reusable
   single-agent method components. They depend on public Platform contracts
   only. A downstream paper can import ReferenceReActMethod, ReferenceReflexionMethod, ReferencePlanAndSolveMethod,
   Working/Episodic/Vector Memory, and ToolRegistry, then replace only its
   novel policy/component.
3. orchestration/multi_agent/ is a higher orchestration tier. It owns explicit
   agent-node topology, message delivery, GroupChat, Debate, and Hierarchical
   coordination. It does not own agent cognition, memory, scientific results,
   or provider state.

The dependency direction is one-way:

downstream project -> components / orchestration
                   -> noetrium.contracts
                   -> explicit injected noetrium_platform implementation

noetrium_platform never imports root extensions, and no root extension owns a
global registry. Composition constructs each registry/topology and injects it
into a method. The root packages are the only canonical extension paths.

## High-level Agent Research Kit boundary

The stable product facade also exposes
\`noetrium.platform.bind_agent_research_runtime\`. It composes the existing
environment-neutral \`AgentCognitionLoop\` from typed observation, planner,
skill, action, memory, safety, completion, evidence, progress, and optional
diagnostic ports. The paper chooses the policies and providers; Noetrium
owns sequencing, budgets, checkpoint restoration, and diagnostic failure
handling.

For multimodal papers, \`MultimodalAgentObservationPort\` composes a normal
observation source with an arbitrary content-part source. Parts remain
content-addressed and preserve modality, ordering, timing, coordinate-frame,
and source-reference metadata. The adapter does not assume a vendor or a
finite list of modalities.

Model calls use the same public composition boundary:
noetrium.platform.complete_project_model records and fences a qualified
generation request, while invoke_multimodal_model passes arbitrary multimodal
parts through a provider-owned codec and content store. The model body,
modality interpretation, and response decoding remain method/provider owned;
request identity, recording, endpoint invocation, and response provenance
remain Noetrium-owned.

## Paper reproduction patterns

| Paper contribution | Reuse | Downstream change |
| --- | --- | --- |
| ReAct-like control loop | ReferenceReActMethod | decision policy |
| Self-reflection/refinement | ReferenceReflexionMethod | reflection policy |
| Explicit planning | ReferencePlanAndSolveMethod | planner/solver |
| Short-term context | WorkingMemory | capacity or item policy |
| Long-term episodes | EpisodicMemoryStore | retrieval policy or durable adapter |
| Embedding retrieval | VectorMemoryStore | embedder or indexed store |
| Tool use | ToolRegistry | typed definitions and handlers |
| Debate/group/hierarchy | orchestration.multi_agent | node implementations and topology |

A whole-method paper can implement ReferenceAgentDecisionPort and run unchanged through
the same public host, or replace the full loop without editing Platform source.
A novel component should remain downstream when it is scientific novelty; only
generic reusable mechanisms belong in components.

These deterministic reference components provide in-memory defaults plus crash-durable SQLite adapters. Agent progress is an append-only event/checkpoint stream; graph execution exposes checkpoint history and exact-snapshot replay; multi-agent coordination can persist its transcript and resume from a SQLite journal. A
claim-grade project binds Platform artifact/evidence ports around them
and records the exact component/source/configuration identities.
