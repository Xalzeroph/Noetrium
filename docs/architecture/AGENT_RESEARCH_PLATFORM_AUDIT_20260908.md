# Noetrium Agent Research Platform Audit

Date: 2026-09-08
Scope: current Noetrium master on the canonical Linux server, including public
facades, reference components, participant Agent runtime, model/environment
capabilities, orchestration, experimentation, evidence, and publication.

## Executive verdict

Noetrium is a strong research infrastructure substrate, but it is not yet a
fully optimized Agent Research Kit. It can express arbitrary whole-method
control graphs through `ResearchMethodProgram` and arbitrary component methods
through typed ports. It already contains a durable environment-neutral
`AgentCognitionLoop` with observation, memory, planning, skills, safety,
actions, completion, evidence, progress, diagnostics, and checkpoints.

The gap is composition ergonomics and convergence: high-level runtime
implementations are deeper than the stable downstream facade, the older
reference-agent method family and newer cognition runtime are separate
archetypes, and multimodal contracts existed without an end-to-end capture and
serving composition. A paper author should not have to rediscover or wire the
same lifecycle, recovery, memory, evidence, and experiment boilerplate.

This audit therefore distinguishes:

- Expressible: the method can be represented without changing Noetrium.
- Reusable: a stable upstream component already implements the common mechanism.
- Fast path: a public composition entrypoint makes the common case short.
- Reliable: identity, budgets, checkpoint, effect/evidence, and failure behavior
  are enforced at the shared boundary.

## Capability matrix

| Agent research need | Expressible | Reusable upstream | Fast/reliable path | Current finding |
| --- | --- | --- | --- | --- |
| Arbitrary novel control graph | Yes | ResearchMethodProgram, MethodGraphProgram | Partial | Whole-method host is sound; trial/run composition still needs a single recipe. |
| ReAct/tool loop | Yes | ReferenceReActMethod, AgentCognitionLoop | Partial | Two parallel method archetypes; the newer loop has the stronger lifecycle. |
| Reflection, planning, ToT/GoT/MCTS | Yes | planner/reflection/graph ports | Partial | Method state remains paper-owned; checkpoint host exists. |
| RAG and memory agents | Yes | AgentMemoryPort, memory stores, evidence ports | Partial | Semantic retrieval remains downstream, which is correct; adapter setup is verbose. |
| Tool/function use | Yes | ToolRegistry, capability/effect ports | Strong | Authorization, risk class, audit, and typed results are reusable. |
| Multimodal/VLM/vision/audio/video | Yes | open MultimodalPart/Request/Response, projector | Partial | Open-world contracts now exist; capture and provider codecs must be injected. |
| Embodied/web/GUI/robotics | Yes | observation/action/environment ports | Partial | Provider boundary is sound; common adapters are domain-specific. |
| Multi-agent/debate/hierarchy | Yes | topology, journal, coordinators | Partial | Durable coordinator implementations need a stable high-level public entrypoint. |
| Online learning/RL/MARL | Yes | method host, env, study, checkpoint seams | Partial | Tensor/replay/optimizer/simulator remain provider-owned; rollout recipe is missing. |
| Model serving/streaming | Yes | qualified model binding, capability invocation/stream | Partial | Generic typed capability exists; paper planner still hand-builds request bodies. |
| Ablation/seeds/repetitions | Yes | StudyMatrixBinding, assignments, run identity | Strong | Public study path is reusable; complete run/evidence recipe should be one composition. |
| Evaluation/statistics/plots/report | Yes | research workbench/lifecycle | Strong | Common workflow is centralized; specialized analyses remain adapters. |
| Crash recovery/replay | Yes | run control, checkpoint, reconciliation, evidence | Partial | Infrastructure is rich; resource exhaustion and cross-layer smoke tests remain blockers. |
| Performance and scale | Yes | structured concurrency, bounded queues | Partial | Correctness exists, but watch/fd pressure and high-volume backends need hardening. |

## What is already good

1. The public contracts are typed, immutable, digest-bearing, and generally
   provider-neutral. This is the right foundation for arbitrary paper methods.
2. The whole-method seam does not force a paper into a ReAct or memory-shaped
   ABI. A paper can own its own task, input, result, graph, and state.
3. The participant Agent runtime is already higher-level than a collection of
   ports: it sequences cognition phases and centralizes budgets, safety,
   progress, diagnostics, and checkpoint restoration.
4. Model and multimodal boundaries use content references and provider-owned
   codecs. Noetrium does not hard-code one vendor or one image/text recipe.
5. Experimentation and publication have shared identities and lineage, so a
   downstream paper need not create another measurement, statistics, or figure
   authority.

## Gaps that matter for the next paper

### P0: one public Agent Research Runtime composition

Expose one stable product-facade binding that composes the existing
environment-neutral `AgentCognitionLoop`. It must accept arbitrary injected
ports, reject incomplete port bundles before execution, expose run/checkpoint
and diagnostic operations, and avoid adding a second loop implementation.

Status: implemented in `noetrium.platform.bind_agent_research_runtime`.

### P0: one multimodal observation composition

A base observation source and an arbitrary content-part source need a reusable
adapter. The adapter must preserve content references, modality ids, ordering,
timestamps, coordinate frames, and source provenance, while leaving
interpretation and serialization to the method/provider.

Status: implemented as `MultimodalAgentObservationPort`; it is open-world and
does not assume image, audio, video, or a particular VLM.

### P1: converge the public method story

The legacy reference ReAct/Reflexion/Plan-and-Solve components remain useful
quick starts. The participant cognition loop is the richer durable runtime.
Document the choice explicitly and add adapters so papers can start with a
reference method and graduate to a custom graph without changing experiment
identity or evidence plumbing.

### P1: high-level model and environment recipes

Provide composition helpers around the existing typed model capability and
environment ports. A downstream planner should supply method-owned typed
payloads or a provider codec, not reimplement request envelope, provenance,
recording, timeout, retry, and response validation.

Status: complete_project_model now centralizes qualified generation request
recording, endpoint invocation, and response provenance fencing.
invoke_multimodal_model additionally routes arbitrary multimodal parts through
a provider-owned codec and content store. Serialization and response
interpretation remain provider/method-owned by design. Environment
branch/readiness/effect composition is still provider-specific.

### P1: multi-agent and rollout recipes

Expose coordinator composition and a standard single-trial rollout recipe
that connects method, environment, model, memory, run control, checkpoint,
measurement, evidence, and artifact publication. Keep scientific semantics
downstream, but make the mechanics one reusable path.

### P2: resource-safe reliability

The current full Noetrium suite has a server baseline problem: 99 failures
were observed after shared Linux directory-watch/inotify exhaustion, while an
isolated forensics test passed. This is not evidence that the new multimodal
contracts fail. Before formal SEM experiments, rerun in a fresh process budget
and add resource-safe test/runner diagnostics; do not silently change host
sysctls or kill unrelated processes.

### P2: backend adapters, not core vendor lock-in

GPU/distributed training, vector indexes, simulator SDKs, browser/robotics
drivers, VLM serialization, Arrow/Parquet, and specialized statistics should be
provider adapters. The acceptance criterion is that each adapter returns the
existing identity-bearing contracts and does not duplicate scheduler,
measurement, evidence, or publication authorities.

## Target paper-author experience

A new paper should normally choose one of two paths:

1. Custom method: implement `ResearchMethodProgram` or `MethodGraphProgram`
   for the novel control graph, then bind the shared trial/run and analysis
   recipe.
2. Composed Agent: implement only the novel planner, skill, observation,
   memory, model, or environment port and use the public Agent Research Runtime
   binding.

Both paths must produce the same run identity, checkpoint/evidence lineage,
measurements, study assignments, and report artifacts. A method-specific
backend is acceptable; method-specific lifecycle plumbing is not.

## Acceptance gates before formal experiments

- No downstream import of Noetrium private runtime modules when a public facade
  exists.
- The paper's novel method is expressed through one of the two method paths.
- Multimodal inputs are content-addressed and preserve arbitrary modality
  provenance.
- Model requests use typed capability invocation and provider-owned codecs.
- Every trial has frozen assignment, run identity, checkpoint/recovery policy,
  measurements, evidence, and artifacts.
- Fresh-process targeted suite passes, and full-suite resource limits are
  understood and recorded.
- Only after these gates pass should SEM formal experiments begin.

