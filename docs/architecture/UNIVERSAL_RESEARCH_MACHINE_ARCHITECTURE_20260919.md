# Universal Research Machine Architecture

> Status: **Normative**
> Effective date: 2026-09-19
> Compatibility policy: **none**. Superseded execution APIs are removed, not aliased.
> Execution truth: Machine Journal.

## 1. Architectural decision

Noetrium is a Research OS built around a small family of programmable research
Machines. A subsystem qualifies for this family only when downstream papers may
legitimately redefine its transition semantics.

The programmable domains are:

1. **Method** — algorithm semantics through MethodProgram / UMM.
2. **Runtime** — execution semantics: turns, events, context, communication,
   logical scheduling, synchronization, capability mediation, visibility,
   recovery and intervention.
3. **Participant** — actor-local state and role/session behavior for agents,
   user simulators, judges, humans and other research actors.
4. **Environment** — state/action/observation world dynamics.
5. **Memory** — paper-defined memory evolution semantics.
6. **Evaluation** — interactive or stateful evaluator/verifier execution.
7. **Optimization** — search/evolution/architecture optimization over research
   programs and bindings.
8. **Experiment** — adaptive scientific protocol execution.
9. **Research Run** — thin run-level topology/frozen-binding lifecycle.

Facts, immutable identities, content, evidence, projections, pure policy,
physical scheduling and provider mechanics are not promoted to Machines merely
because they are complex.

## 2. One execution substrate

```text
MethodProgram ----------------------------+
                                          |
ResearchProgram --------------------------+
  kind = runtime                          |
       | participant                      |
       | environment                      |
       | memory                           |
       | evaluation                       |
       | optimization                     |
       | experiment                       |
       | run                              |
                                          v
                                  MachineExecutor
                                          |
                                  TransitionProposal
                                          |
                                    Machine Journal
                                          |
                                  accepted transition
```

`MachineExecutor` is the kernel acceptance/execution coordinator. The old
`MachineRuntime` name and module are retired. **Runtime** is reserved for
paper-programmable execution semantics.

A Program interpreter may propose state change, events, child commands, evidence
references, artifact references and effect intents. It cannot commit truth.
Only Machine Journal acceptance makes the transition authoritative.

## 3. ResearchProgram IR

All non-Method programmable domains use one `ResearchProgram` IR:

```text
ResearchProgram
├── immutable program identity/digest
├── MachineKind
├── state schema
├── entrypoint
└── ProgramNode*
    ├── arbitrary operation identity
    ├── immutable configuration
    ├── capability requirements
    └── next-node relation
```

The kernel-level command vocabulary is intentionally tiny:

- `program.start`
- `program.step`
- `program.resume`

Paper-specific operation names are resolved through an explicit
`ProgramHandlerRegistry`. Therefore a downstream paper can introduce a new
runtime, memory, evaluation or optimization operation without adding a platform
enum, runner or controller.

## 4. Runtime as a meta-machine

Runtime is not process management. Runtime is the semantics of *how a research
method executes*.

A RuntimeProgram may redefine:

- turn and event boundaries;
- context construction/projection;
- message routing and communication;
- logical participant scheduling;
- model/tool/capability mediation;
- private/shared state visibility;
- synchronous, asynchronous and barrier behavior;
- interruption, yielding and human intervention;
- retry, rollback, compensation and recovery policy.

These are first-class Runtime concerns, not hard-coded Agent loop phases.

OS process, service, container, host, session and server lifecycle mechanics are
infrastructure/provider concerns. They may be journaled where authoritative but
must not occupy the research Runtime namespace.

## 5. Participant

Agent is not a Machine kind. A software agent is one ParticipantProgram.

The same Participant domain hosts:

- model-driven agent;
- simulated user;
- judge/reviewer;
- teammate/opponent;
- human proxy;
- specialized research role.

Agent Turn is therefore a reusable ParticipantProgram, not a separate VM.

## 6. Environment

EnvironmentProgram owns paper-definable world transition semantics:

```text
EnvironmentState + Action
             -> Environment transition
             -> EnvironmentState' + Observation
```

Browser, GUI, software sandbox, TextWorld, Minecraft, robotics and simulators
are provider/binding families unless their scientific transition semantics are
explicitly expressed in the EnvironmentProgram.

## 7. Memory

MemoryProgram provides the execution host for arbitrary memory evolution.
No universal memory algorithm is imposed.

Typical paper-defined operations include read/write/query, merge/split,
promote/demote, retract/forget, summarize/consolidate and learned policy
updates. Retrieval score, tiering, reflection and semantic evolution remain
Program semantics.

## 8. Evaluation

EvaluationProgram supports stateful or interactive evaluation: sandbox tests,
trajectory verification, model judges, multi-judge procedures, environment
queries, artifact verification and human evaluation.

Evaluation execution does not itself decide scientific acceptance. Frozen
evaluation identity and claim-relevant result acceptance remain owned by
Experimentation/Evaluation authority.

## 9. Optimization

OptimizationProgram is first-class because agent research increasingly searches
over methods, runtimes, prompts, participant topology, model bindings and whole
agent architectures.

Search algorithms may implement sampling, mutation, crossover, surrogate
updates, ranking, selection, pruning, expansion and stopping without creating
new platform runners.

Task-level trajectory search remains Method/Runtime semantics; search over the
research design itself belongs to Optimization.

## 10. Experiment

ExperimentProgram interprets frozen scientific protocol plus allowed adaptive
decisions. Trial/assignment execution must become journal-visible transitions,
rather than being hidden inside an opaque matrix runner.

Study/Experiment/Run identity remains frozen authority. The Experiment Machine
executes that protocol; it does not rewrite scientific identity.

## 11. RuntimeModule subprogram rule

A paper may need to DIY one execution dimension without replacing the whole
Runtime. Those dimensions are first-class **RuntimeModules**, not independent
Machines:

- Context module;
- Communication module;
- Logical Scheduling module;
- Capability Mediation module;
- Visibility module;
- Recovery module;
- Intervention module;
- Turn/Event modules.

`RuntimeModuleBuilder` authors one concern-local graph.
`RuntimeProgramComposer` namespaces module nodes, validates explicit
cross-module links and compiles the composition into exactly one
`ResearchProgram(kind=runtime)`. Modules own no journal, mutable runtime state
or durability history.

Therefore a paper can replace only its context projection policy while reusing
the same communication and scheduling modules, or replace only logical
scheduling while preserving every other Runtime semantic. The resulting
program digest records the exact module composition.

A new Machine kind requires proof that it owns an independent paper-variable
state-transition lifecycle. Complexity alone is insufficient.

## 12. Authority invariants

1. Machine Journal is the only accepted execution transition history.
2. Program handlers propose; kernel authority accepts.
3. Snapshot is an accelerator, never a second truth source.
4. External effect uncertainty is never collapsed into ordinary failure.
5. Provider state does not silently become scientific truth.
6. A projection, cache, log, metric or UI cannot become a Machine authority.
7. Program state is serializable and replayable from accepted transitions.
8. Paper-specific operations extend Programs/handlers, not the kernel.
9. No compatibility aliases or dual execution paths are retained after migration.
10. A downstream paper implements only its novel semantics.

## 13. Migration target

Delete or demote domain-local `Runner`, `Loop`, `Controller`,
`Coordinator`, `Manager` and independent history implementations whenever
their state transition behavior is representable by the universal Machine
substrate.

The end state is not "many VMs". It is a small family of research meta-machines
over one kernel, with most papers expressed as Programs.


## 14. Universal Program hosting and Machine nesting

All non-Method research Machines use one `ResearchProgramHost`. Runtime,
Memory, Environment, Evaluation, Optimization, Experiment and Run must not
create domain-specific Program hosts. The host binds a `ResearchProgram`,
operation handlers and the shared Machine Journal; it owns no research truth.

Nested research computation is also part of the universal ABI:

```text
Parent Program node
      |
      +-- ChildResearchMachineExecutor
              |
              +-- ResearchProgramHost
              |       |
              |       +-- child Machine Journal
              |
              +-- authoritative MachineCut
                      |
                      +-- ChildMachineLink
                              |
                              v
                     parent Machine commit
```

`ProgramNodeResult.child_links` and `MethodNodeResult.child_links` carry the
same typed `ChildMachineLink`. Therefore both ResearchProgram parents and UMM
MethodProgram parents can journal nested Machines without a domain-specific
orchestration ledger.

The child journal remains the child's execution truth. The parent journal owns
only the immutable parent/child relation and the exact child cut/result
reference. A supervisor may coordinate lifecycle but cannot become either
Machine's truth source.

This enables compositions such as:

- MethodProgram -> OptimizationMachine for agent/workflow architecture search;
- RuntimeProgram -> EvaluationMachine for interactive verification;
- ParticipantProgram -> MemoryMachine for learned memory policy;
- ExperimentProgram -> child Run/Optimization Machines for adaptive protocols.

A paper that changes the outer algorithm and an inner search algorithm should
express both layers explicitly rather than flattening them into one oversized
MethodProgram or writing a custom nested runner.

## 15. No opaque trial or matrix runners

Scientific trial execution is Program-backed. The platform no longer exposes
an arbitrary Python `ExperimentTrialProtocol.run()` extension point or a
fixed `TrialMatrixExecutor`. Downstream trial semantics are authored as a
`RuntimeProgramTrialProtocol`; assignment/matrix progress is an
ExperimentMachine program.

This preserves downstream freedom while making every control-flow decision
journal-visible, resumable and identity-bound.


## 2026-09-19 convergence addendum: Host + sub-IR architecture

### One host for all non-Method programmable research Machines

Every non-Method `ResearchProgram` MUST be bound through
`ResearchProgramHost`. Domain code MUST NOT assemble its own
`MachineExecutor + ProgramLock + ProgrammableMachineInterpreter +
ResearchMachineSession` stack.

The only deliberate exception is Method/UMM, whose MethodProgram interpreter
has its own specialized semantic ABI while committing through the same Machine
kernel and Journal authority.

```text
ResearchProgram
    + operation handlers
    + dependency identity
            |
            v
   ResearchProgramHost
            |
            +-- ProgramLock derivation
            +-- Machine family binding
            +-- MachineExecutor
            +-- ProgrammableMachineInterpreter
            +-- ResearchMachineSession
            |
            v
       Machine Journal
```

This rule is architectural, not ergonomic. It prevents each new paper family
from growing a private executor/session construction path and keeps downstream
DIY at the Program/handler boundary.

### Machine domains versus sub-IRs

A new paper-variable concern does not automatically justify a new Machine.

Current first-class stateful research Machine domains are:

- Runtime;
- Participant;
- Environment;
- Memory;
- Evaluation;
- Optimization/Search;
- Experiment;
- Research Run;
- Method through its specialized UMM path.

Local execution semantics that do not require an independent durable identity
MUST remain sub-IRs. Current examples include:

- ContextProgram / model-view projection;
- RuntimeModule(Context);
- RuntimeModule(Communication);
- RuntimeModule(Logical Scheduling);
- RuntimeModule(Synchronization);
- RuntimeModule(Capability Mediation);
- RuntimeModule(Recovery);
- RuntimeModule(Intervention);
- RuntimeModule(Visibility).

`ContextProgram` is intentionally pure. It defines ordered model-view blocks,
renderers, required/optional admission and loss-explicit projection receipts,
but it owns no Journal. When context construction itself is part of a studied
runtime, its digest is referenced from a `RuntimeModule(CONTEXT)` and the
enclosing RuntimeMachine owns execution truth.

### Provider and exported-snapshot rule

A provider may maintain operational mechanics necessary to interact with an
external system. A checkpoint/export codec may materialize a portable snapshot.
Neither is an independent source of scientific truth.

The authority order is:

```text
Machine Journal
    > accepted Machine state
    > verified snapshot/export artifact
    > provider-local operational state
    > diagnostic cache/log
```

Examples:

- Environment dynamics/provider may perform external I/O, while EnvironmentMachine
  owns accepted scientific environment state.
- State-machine environment checkpoint bytes are export/import artifacts derived
  from EnvironmentMachine state, not a second live state store.
- Run lifecycle effects/reconciliation are providers, while RunMachine owns phase,
  prepared control operation, checkpoint head and control revision.
- Context/history projections are model views; they never mutate durable host truth.

### No fixed research-policy managers

Platform code MUST NOT introduce a stateful `*Manager`, `*Controller`,
`*Runner`, or `*Loop` for a policy that can legitimately vary across papers.

Such semantics belong in a Program, RuntimeModule, ContextProgram, or operation
handler. Stateful fixed managers are allowed only for infrastructure/provider
mechanics that are explicitly outside scientific semantics.

The following legacy patterns have been removed under this rule:

- AgentActionManager;
- AgentSelfPrompter;
- AgentGoalGraph;
- ReactiveModeController;
- fixed InMemorySkillLibrary authority;
- Agent memory checkpoint authority;
- Agent coordination/conversation checkpoint authority;
- fixed ContextAction and AgentTurn Python trial loops;
- independent RunControl ledger/phase authority.

Their research semantics are now expressed through Participant, Runtime, Memory,
Experiment/Run Programs or pure sub-IRs.
