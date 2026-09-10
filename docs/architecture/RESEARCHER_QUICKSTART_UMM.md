# Researcher Quickstart: Universal Method Machine

The Universal Method Machine (UMM) is Noetrium's execution kernel for reproducible research methods. A researcher defines a typed method program; the platform owns scheduling, checkpoints, recovery, evidence validation, and receipts.

## The shortest path

1. Import method contracts from `noetrium.contracts.systems.execution__workflow`.
2. Create a `MethodProgramIdentity` and build a method with `MethodProgramBuilder`.
3. Bind the runtime through `noetrium.platform.bind_universal_method_machine()`.
4. Run the program with an `ExecutionContext` and a `MethodRuntimeContext`.
5. Inspect the `MethodRunResult`, checkpoint receipt, evidence status, and failure metadata.

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

## Choosing the method surface

Use native method nodes when the work is a deterministic or stateful research procedure. Use an adapter node when an existing provider, agent, or external tool already owns the operation. Both routes produce the same typed node requests, results, evidence, and receipts.

A node can declare input and output schemas through `MethodSchemaPort`. The machine validates the program input, restored state, node input, and node output at the boundary. This keeps invalid intermediate values from silently entering a run.

## Agents and long-running work

Use an `AGENT` node with `MethodAgentLoopPort` when the method needs iterative planning or tool use. The agent may return a checkpoint payload; the machine persists it and passes it back on resume. Async agent implementations may provide `run_async` without a synchronous `run` implementation.

## Reproducibility checklist

- Give every method and node a stable identity and version.
- Keep side effects behind typed ports and record their receipts.
- Treat `UNKNOWN` as a real state; do not convert missing evidence into success.
- Provide a checkpoint store appropriate to the deployment; the default in-memory store is for local runs and tests.
- Keep research artifacts and evidence linked to the run identity.

For the complete platform model, read `PLATFORM_ARCHITECTURE.md`, `UNIVERSAL_RESEARCH_HARNESS_DESIGN.md`, and `COMPOSITION_GRAPH_AND_EVENT_SPINE_DESIGN.md`.
