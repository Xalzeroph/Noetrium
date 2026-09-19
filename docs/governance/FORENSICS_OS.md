# Forensics OS

## Required evidence layers

### 1. Structured event ledger
Every important transition emits an event with:

- run/study/condition/lifetime/branch
- task/decision-cycle
- trace/span/parent-span
- operation/component
- model/prompt/method/environment generations
- artifact/state/effect references
- monotonic sequence and wall time

### 2. Raw process evidence
Model, environment, bridge, worker and study subprocesses use complete segmented stdout/stderr capture. Never switch to `/dev/null` or discard a failed stream.

### 3. FailureEnvelope
Every expected boundary failure gets:

- stable domain and code
- exact stage
- cause chain digest
- data/comparability/scientific risk
- state reads/writes
- effect certainty
- mechanically authorized next action

Unexpected programming bugs should still preserve the traceback and be classified as software defects; do not reinterpret them as retryable infrastructure failures.

## Operator commands to converge toward

```text
evoctl status RUN
evoctl why RUN FAILURE_ID
evoctl locate RUN ANY_ID
evoctl trace RUN TRACE_ID
evoctl decision-cycle RUN DC_ID
evoctl last-writer RUN STATE
evoctl model-run MODEL_RUN_ID
evoctl process-run PROCESS_RUN_ID
evoctl checkpoint CHECKPOINT_ID
evoctl prompt-request REQUEST_ID
evoctl metrics RUN --around FAILURE_ID
evoctl crash-bundle RUN FAILURE_ID
```

## Crash bundle contents

A crash bundle should include pointers/hashes, not uncontrolled copies, for:

- failure envelope
- causal graph slice
- recent state mutations
- exact model stack identity
- prompt bundle identity
- request/response transcript slice
- process stdout/stderr segment manifest
- host/GPU telemetry window
- latest verified checkpoint
- environment effect receipts
- executable recovery plan

## Triage SLA target

The system should make the following questions answerable mechanically:

1. What failed?
2. Where exactly did it fail?
3. What was the last proven-good state?
4. Did an external side effect possibly occur?
5. Did authoritative scientific state change?
6. Is the run still scientifically usable?
7. What exact action is safe next?
8. What IDs/commands reproduce the evidence?

## Source-audit implementation rule

Forensic source audits may optimize AST traversal by extracting literal call arguments/keywords once per call node and reusing those values. This is an implementation optimization only: failure-domain/code/stage authority, free-form bypass detection, path identity and fail-closed catalog validation must remain unchanged.
