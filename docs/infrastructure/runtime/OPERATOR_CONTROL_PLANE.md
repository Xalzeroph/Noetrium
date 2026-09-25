# Operator Control Plane — Round 07

The operator surface is deliberately read-mostly and joins evidence; it does not become a new owner of scientific or runtime state.

## Debug path

```text
failure_id
  -> why
  -> exact component/stage/task/decision-cycle/operation
  -> correlated timeline
  -> recent authoritative state writers
  -> evidence-chain verification
  -> exact recovery action
```

Commands:

```bash
python scripts/noetrium_forensics.py status RUN_ROOT
python scripts/noetrium_forensics.py why RUN_ROOT FAILURE_ID
python scripts/noetrium_forensics.py locate RUN_ROOT OPAQUE_ID
python scripts/noetrium_forensics.py timeline RUN_ROOT OPAQUE_ID --seconds 30
python scripts/noetrium_forensics.py last-writer RUN_ROOT RUN_ID STATE_NAME
python scripts/noetrium_forensics.py verify-evidence RUN_ROOT
```

The control plane never silently changes a model, precision, context, prompt, method, environment, seed, workload, or acceptance rule.

## One-click exact recovery

`ExactRecoveryCoordinator` executes the immutable `RecoveryPlan` in order. Every step must return evidence references. The first failing step terminates the transaction and raises `RecoveryExecutionError` containing the exact step and completed prefix. There is no alternate-model branch and no quality-lowering fallback.
