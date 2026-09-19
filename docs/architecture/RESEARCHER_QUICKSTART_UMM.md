# Researcher Quickstart: Universal Method Machine

> Current architecture note: UMM is the universal research-method interpreter. It is **not** a second durability or execution-truth authority. Accepted scientific execution truth is committed through the Machine executor and Machine Journal as defined by `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md`.

A researcher defines a typed `MethodProgram`; the platform supplies the reusable method interpreter, typed capability/effect boundaries, Machine-backed transition authority, checkpoint/recovery mechanics, evidence/artifact integration, and experiment/runtime composition.

## The shortest path

1. Import method contracts from `noetrium.contracts.systems.execution__workflow`.
2. Create a `MethodProgramIdentity` and build a method with `MethodProgramBuilder`.
3. Construct the normal `ExecutionContext` and `MethodRuntimeContext` for the run.
4. Bind method transition truth to the Machine executor through the platform composition path. The high-level platform run path does this automatically when the runtime has no pre-bound transition authority.
5. Execute the method with UMM. UMM interprets the method graph; accepted node-level execution truth is recorded through the bound Machine transition authority.
6. Inspect the method result together with the authoritative Machine/run/effect/evidence records for the run.

The public UMM binding remains available:

```python
from noetrium import platform
from noetrium.contracts.systems.execution__workflow import (
    MethodIdentity,
    MethodNodeResult,
    MethodProgramBuilder,
    MethodProgramIdentity,
)

identity = MethodProgramIdentity(
    MethodIdentity("lab.example.answer", "1", "1", "1")
)
program = (
    MethodProgramBuilder(identity, entrypoint="answer")
    .return_node(
        "answer",
        "lab.example.answer.v1",
        lambda request: MethodNodeResult(value={"answer": 42}),
    )
    .build()
)

machine = platform.bind_universal_method_machine()
result = machine.run(program, runtime=runtime_context)
```

This direct binding is a method-interpreter convenience surface. For a reproducible or resumable run, the supplied `runtime_context` must carry the appropriate Machine-backed transition authority; the platform composition path uses `bind_machine_method_runtime(...)` internally when needed.

## Authority model

The current flow is:

```text
MethodProgram
    ↓
UMM interpreter
    ↓
node/control decision
    ↓
MachineMethodTransitionAuthority
    ↓
MachineExecutor
    ↓
Machine Journal commit
```

A method node may compute a result, call a pure capability, prepare an external effect, interrupt, or request a checkpoint. None of those facts become authoritative merely because Python code returned successfully. The owning authority must accept the corresponding transition/effect/evidence record.

A UMM checkpoint is not an independent research-state history. Durable recovery must remain bound to an accepted Machine journal cut and the exact program/binding identities required by the run.

## Choosing the method surface

Use native method nodes when the work is a deterministic or stateful research procedure. Use an adapter node when an existing provider, agent, or external tool already owns the operation. Both routes use the same typed method request/result boundary and must enter the same authoritative transition/effect/evidence path.

A node can declare input and output schemas through `MethodSchemaPort`. UMM validates the program input, restored state, node input, and node output at the method boundary. Schema validation does not itself make a result authoritative; it is one prerequisite before the owning Machine/effect/evidence authority accepts the fact.

## Agents and long-running work

Use an `AGENT` node with `MethodAgentLoopPort` when the method needs iterative planning or tool use. Agent cognition remains method semantics: `AgentCognitionLoop` and similar reusable loops are reference method/program compositions rather than independent platform execution authorities.

Long-running execution should bind the method runtime to crash-durable Machine storage. Resume begins from an accepted journal cut, optionally accelerated by a verified snapshot/checkpoint. Do not create a paper-local checkpoint history that can diverge from Machine execution truth.

## Effects and external capabilities

Models, tools, environments, remote runtimes, and other external systems enter through typed capability/provider boundaries. A successful transport call is not automatically a verified research effect.

- Pure capability results may be consumed as method inputs after their contract checks pass.
- Effectful operations must preserve intent, idempotency/certainty, receipt, and reconciliation semantics.
- `UNKNOWN` effect certainty is a real state and must never be converted to success by retry convenience logic.
- Provider state is implementation state unless and until the owning Noetrium authority accepts the corresponding fact or receipt.

## Reproducibility checklist

- Give every method and node a stable identity and version.
- Freeze the method program digest and all recovery-relevant run bindings.
- Bind method transition truth to the Machine executor rather than maintaining a second paper-local execution history.
- Keep side effects behind typed ports and record their intents/receipts through the effect authority.
- Treat `UNKNOWN` as a real state; do not convert missing evidence into success.
- Use a crash-durable Machine journal/snapshot composition for resumable deployments.
- Treat resume as recovery from an accepted journal cut, not as replay from an arbitrary local object snapshot.
- Keep research artifacts and evidence linked to the same run/machine/program identities.
- Keep benchmark success criteria, planner policy, memory semantics, reflection logic, and other paper-specific scientific semantics downstream unless they are genuinely reusable platform contracts.

## What to read next

Read these in order:

1. `CURRENT_ARCHITECTURE_AUTHORITY.md` — documentation precedence and supersession rules.
2. `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md` — current authority topology and execution-truth contract.
3. `NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md` — long-form end-state rationale and Machine architecture.
4. `UNIVERSAL_RESEARCH_HARNESS_DESIGN.md` — MethodProgram/UMM design history and method-expression model; interpret durability ownership through the newer authority-consolidation specification.


## Runtime customization after UMM

MethodProgram answers *what algorithm runs*. RuntimeProgram answers *how that
algorithm is executed*: context projection, communication, logical scheduling,
capability mediation, visibility, recovery, intervention, and turn/event
semantics.

Use `RuntimeModuleBuilder` when a paper changes only one of those concerns,
then compose modules with `RuntimeProgramComposer`. Do not implement a new
runner merely to change a context or scheduling rule.


## Nested universal Machines

When one research method invokes another research computation, do not write a
custom runner. Use `ChildResearchMachineExecutor` with a
`ResearchProgramHost`, then return the resulting `ChildMachineLink` from the
parent node.

For example, an automated agent-design method should normally be represented as
an outer MethodProgram whose design-search step executes an OptimizationProgram
child. The Optimization Machine owns candidate/search state; the Method Machine
owns the outer algorithm and records the exact child cut.

The same pattern applies to Runtime -> Evaluation, Participant -> Memory and
Experiment -> Optimization/Run nesting. Child state is never copied into the
parent as a second authority.
