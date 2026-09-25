# AI Infrastructure System

The AI infrastructure system owns reusable model and inference-runtime capabilities. It does not choose a preferred model, engine, host, accelerator placement, or scientific role policy.

## Ownership topology

```text
model identity/catalog
        ↓
asset acquisition + verification
        ↓
deployment qualification
        ↓
runtime materialization
        ↓
serving endpoint + route identity
        ↓
request / prompt / telemetry contracts
```

Each stage has a distinct authority and durable identity. A later stage may consume evidence from an earlier stage but must not silently recreate or override that authority.

## Model identity

A model identity freezes the fields required by the consuming workflow, including logical/model identity, exact revision, serving engine and version, dtype, quantization state, context contract, and other compatibility-critical attributes.
## Asset and deployment qualification

Model bytes and native runtime assets are acquired through artifact/runtime-asset authorities and verified before serving qualification. A path existing on disk is not sufficient evidence of model or runtime readiness.

Deployment qualification starts from read-only host capability facts and produces an exact plan. Materialization then creates the required runtime without changing the frozen plan. Runtime qualification proves that the materialized endpoint actually satisfies the requested model stack and placement.

The generic operator flow is:

```bash
noetrium-manage --config <management-config> deployment qualify \
  --model-id <model-id> \
  --model-path <verified-model-path>

noetrium-manage --config <management-config> deployment apply-qualification <plan-digest> \
  --environment-id <managed-runtime-id>

noetrium-manage --config <management-config> deployment runtime-qualify <application-digest>
```

Exact CLI fields depend on the selected provider capabilities; downstream repositories own the actual values.
## Serving and role routing

A qualified endpoint is identified independently from the logical role that consumes it. Multiple roles may share one endpoint or route to different replicas, but route identity, model identity, prompt identity, and runtime qualification remain separately observable.

The request layer must not infer a model fallback, precision downgrade, context downgrade, or alternate engine merely to keep execution moving. Any compatibility-changing substitution is a new explicit binding.

## Evidence boundary

Qualification evidence, serving telemetry, and request traces prove operational facts. They do not by themselves establish downstream scientific claims. Downstream applications decide how qualified model evidence participates in their own run admission and result closure.

## Extension rule

New model families and serving engines enter through the smallest existing model/runtime provider contract. The upstream platform should gain a new generic contract only when the capability itself is new, not merely because one downstream application selected a different model or engine.

## Durable model-state decoding

Model assets, desired deployments, applied launch snapshots, controller state, qualification receipts, and model request envelopes are durable authority records rather than permissive configuration inputs. Their persisted readers therefore require the exact documented field set and exact JSON value types.

Readers must not repair schema drift with `str()`, `int()`, `float()`, omitted-field defaults, tuple coercion, or unknown-field tolerance. Checksums protect bytes from accidental alteration, but a checksum-valid document with an invalid internal schema must still fail closed.

External probe adapters may normalize protocol text where that protocol defines textual values; that boundary is distinct from decoding platform-owned persisted truth.