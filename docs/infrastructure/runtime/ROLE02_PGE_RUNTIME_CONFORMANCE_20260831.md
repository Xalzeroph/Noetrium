# ROLE02 PGE runtime conformance — 2026-08-31

Playbook §38.5 and §39.12 require training-worker, streaming/high-bandwidth, dynamic-generation and out-of-process capability lifecycles without paper-specific Runtime APIs.

The existing public contracts are sufficient; no new production authority is introduced.

- `runtime.service.api.ServiceLaunchContract` + `ExactServiceRuntimePort` provide one transport-neutral lifecycle ABI for training and streaming services.
- `resource.compute.api.ComputeRequirement` expresses CPU/RAM/GPU count, minimum GPU memory and labels without provider-private state.
- `resource.allocation.api.EndpointAllocationPort.replace_bound` exposes explicit generation-fenced endpoint rebinding.
- `runtime.process.supervision.api` exposes finite command timeout, explicit supervisor deadline/termination and bounded output retention.

`tests/test_runtime_pge_public_contract_v1.py` proves one training worker and one streaming provider can use those same APIs, that service generation changes identity, and that transport/server/SSH placement is absent from the service contract shape.

Existing adversarial coverage supplies the behavior behind that representation:
- `test_resource_endpoint_atomicity_v2.py`: stale/concurrent generation replacement and restart persistence.
- `test_process_supervision_async_v2.py`: late-spawn fencing, timeout cleanup, cancellation tree reap and bounded pipe retention.
- `test_capacity_admission_scheduling_v1.py`: global/lane/hierarchical backpressure.
- `test_service_quiescence_probe_v167.py`: exact quiescence before replacement/retirement.

This is intentionally composition mechanics, not scientific identity. ROLE04 remains owner of capability/Participant/Model identity and ROLE03 remains owner of run/training/evaluation scientific execution identity.

## Effect-generation fence clarification

`EffectIntent.source_generation` and `EffectCompletionEvidence.consumer_generation`
are intentionally different authorities. For context actions the former is the
Environment generation; the latter can be the Method or Agent generation. They
must not be compared for equality.

The stale-source fence is instead exact request identity. The Environment action
request digest includes `context.generation("environment")`. A successor source
generation therefore produces a different request digest. The effect journal then
fails closed in two independent places: preparing the same logical intent with the
successor source generation conflicts with the already prepared intent identity,
and every result/reconcile transition rejects a request digest different from the
persisted intent digest. Endpoint/service replacement remains separately fenced by
Resource binding CAS and Runtime service generation.

`tests/test_effect_journal_integrity_v1.py` contains adversarial proofs for both
failure modes. This preserves distinct Environment, Method/Agent, Resource and
Runtime generations rather than inventing a universal generation counter.

## Shared large-value carrier fencing

PGE does not require transport-specific Resource enums. Existing `ResourceKind.STORAGE` / `CACHE` represent file or shared-memory carrier allocation, while `NETWORK_ENDPOINT` represents socket transport; `ResourceOwnership.SHARED` records that the carrier itself is shared/external to one consumer generation.

`ResourceLease` owns only resource usage authority: holder scope/generation, fencing token, state and optional TTL. It deliberately has no artifact/content/evidence payload or digest field, so a mutable carrier lease cannot itself become durable scientific evidence.

`tests/test_resource_shared_carrier_fencing_v1.py` exercises file, shared-memory and socket-shaped resources. After generation 1 expires and generation 2 acquires the same carrier, the fencing token advances; a stale token cannot renew generation 2, releasing the expired generation-1 lease cannot disturb generation 2, and a stale generation cannot reacquire while generation 2 is active.

Immutable content/evidence identity remains outside Resource authority. ROLE02 fences reuse of mutable transport; Artifact/Evidence owners attest immutable bytes separately. This satisfies §39.12 without introducing a transport-specific truth store or allowing shared-buffer reuse to rewrite already-attested content.