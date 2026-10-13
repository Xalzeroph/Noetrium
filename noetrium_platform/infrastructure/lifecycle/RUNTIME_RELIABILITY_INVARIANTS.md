# Runtime Reliability Invariants

These invariants govern process, service, server-operation, and runtime lifecycle code.

## Finite temporal controls

Every externally configurable duration that can bound admission, cleanup, polling, transport, process execution, session control, toolchain acquisition, or resource observation must be finite and strictly positive before an external action begins. `NaN`, infinity, zero, and negative durations are configuration errors.

An outer deadline is authoritative. Component-local timers may consume only a finite portion of that budget and cannot disable it.

## Process ownership

`ProcessCommandRunnerPort.execute` accepts a finite positive timeout. The budget covers structured admission and process execution while retaining cleanup time for termination and reaping.

Callers wait on the owned structured task rather than layering an unrelated future timeout around it. A detached caller timeout must never return while an effectful task remains eligible to start later.

## Remote operations

SSH commands, transfers, repository operations, and interactive sessions use explicit finite budgets. Identity-bearing server profiles include the relevant operational limits.

Remote-operation truth is stored as authority-partitioned events. Each operation owns its own causal chain; unrelated operations have no synthetic global total order. Durable decoding rejects generation gaps, invalid causal prefixes, authority drift, noncanonical identities, and impossible transitions.

## Effect certainty

A timeout, cancellation, network loss, process ownership loss, or other failure after a mutating operation may have begun must not be interpreted as `NO_EFFECT`. The original operation remains effect-uncertain until typed reconciliation resolves it. New conflicting mutation stays fenced while uncertainty is unresolved.

## Readiness authority

A READY transition records producer-observed readiness evidence for the exact process/service generation. Heartbeats may advance liveness observations but cannot rewrite the original readiness instant. Consumers project the persisted readiness evidence rather than synthesizing replacement timestamps.

## Durable publication

New durable files are published with the platform's atomic/durable file primitives. Where directory-entry mutation matters, the runtime uses kernel-backed observation and fails closed when it cannot prove the expected namespace transition. A fast path must not weaken publication or recovery correctness.

## Resource preflight

Read-only preflight consumes capacity through the resource candidate interface. It may observe that existing allocations remove a host from eligibility, but preflight cannot grant itself allocate/release authority or duplicate the resource scheduler's filtering logic.

## Validation

Changes to process cleanup, remote effects, readiness, durable publication, or recovery require focused tests for the relevant operating-system behavior plus Linux validation where POSIX process-group, signal, filesystem, or SSH semantics are involved. Validation uses isolated fixtures or explicitly allocated test resources; it must not depend on unrelated research workloads.
