# ROLE04 — Research Method Host

Status: canonical end-state contract as of 2026-09-18.

## Authority

Noetrium has exactly one scientific method execution ABI:

`noetrium_platform.research.execution.workflow.api.MethodProgram`.

A downstream method is compiled into an immutable `MethodProgram` and executed by the Universal Method Machine. There is no second whole-method protocol, graph-program protocol, compatibility adapter, or provider-owned method runtime.

The Machine/Journal path remains authoritative for accepted execution state. Method checkpoints are verified receipts over that authority; they are not a second history.

## Participant/Method boundary

`participant/method` owns participant identity, runtime binding, session services, method-specific recall/task-completion traits and provider lifecycle. It does not own scientific control-flow execution.

`MethodProgramIdentity` joins the scientific program to the frozen method participant implementation/configuration identity. Program execution itself belongs to Research Execution.

## Program boundary

A `MethodProgram` contains:

- exact `MethodProgramIdentity`;
- bounded `MethodGraph`;
- typed `MethodNodeSpec` nodes;
- schema identifiers for state/input/output;
- frozen configuration;
- required capabilities;
- execution class;
- evidence, metric and artifact obligations.

Cross-process values are canonical `JsonValue` plus schema identities. Arbitrary Python object graphs are not an execution ABI.

## Authoring and execution

The canonical path is:

```text
paper/method semantics
        ↓
MethodProgramBuilder / explicit compiler
        ↓
MethodProgram
        ↓
Study + binding requirements
        ↓
ResearchCompiler / workload compiler
        ↓
UniversalMethodMachine
        ↓
Machine / Journal authority
        ↓
measurement + evidence
```

A paper author implements only method-specific nodes and scientific configuration. Platform composition supplies model roles, capabilities, environments, budgets, evidence and execution authority.

## External design research

Project-level agent frameworks are design research inputs only. Their useful
semantics must be rewritten into native MethodProgram/MethodGraph/Machine
contracts before they enter platform implementation.

No project-specific compiler, bridge, adapter, invocation node, checkpoint
translation layer, or compatibility surface is part of the canonical method
host. A scientific reproduction implements the method semantics natively and
binds fidelity evidence at the reproduction layer.

If a design lesson cannot be expressed without preserving the source project's
runtime shape, it is not yet sufficiently absorbed for platform promotion.

## Forbidden architecture

The following are intentionally unsupported:

- whole-method `.run(...)` protocols parallel to `MethodProgram`;
- separate graph invoke/stream program ABIs;
- project-specific method compilers, bridges, adapters, or compatibility facades;
- opaque foreign runtime invocation as a permanent method node;
- provider-owned checkpoint envelopes for scientific method state;
- compatibility aliases for retired method APIs;
- arbitrary Python-only cross-process method values;
- hidden global provider lookup;
- dual writes to Machine/Journal and another method history.

Any downstream reproduction that still assumes one of these patterns must migrate to the canonical program rather than adding compatibility to the platform.
