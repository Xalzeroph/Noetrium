# Participant Typed Capability Contract

ROLE04 exposes exactly one capability invocation authority: canonical
`CapabilityRequest` / `CapabilityResult` through `CapabilityExportSession`.
Typed scientific carriers are a specialization of that authority, not a second
`invoke_typed` path.

A typed input implements `CapabilityInputCarrier`; a typed output implements
`CapabilityOutputCarrier`. Each carrier publishes an exact `schema_id` and a
deterministic semantic `digest()`.

`TypedCapabilityCarrierCodec` maps those values to bytes. The codec identity,
implementation digest, media type, descriptor digest, semantic digest, content
digest and byte size are bound by `TypedCarrierReference`.

Only that verified reference crosses the canonical JSON capability envelope.
Large or high-dimensional scientific payloads remain byte-oriented and therefore
do not need to be flattened into arbitrary JSON values.

`CapabilityCarrierTransportPort` is deliberately only a byte transport seam.
It does not own immutable Artifact/Data identity, retention or catalog authority.
A paper project may bind local shared memory, IPC, remote object transport or a
ROLE05-backed content implementation behind this port without changing the
Participant capability contract.

`FunctionalTypedCapabilityProvider` implements the existing
`CapabilityProviderSession` surface. Consequently typed calls pass through the
same routing, guard/approval/post-policy pipeline, Kernel operation provenance,
and session lifecycle as ordinary capabilities.

The canonical result binds exact `CapabilityProviderIdentity` and the canonical
request digest. Participant generation is copied from
`ExecutionContext.participant_generations` for the configured participant role;
the provider cannot invent a result generation independently of runtime identity.

Codec drift, descriptor drift, provider revision drift, byte corruption,
content-size mismatch and semantic decode drift fail closed before values are
accepted. Equivalent codec implementations with the same exact codec identity
may substitute across process/transport boundaries.

## Effectful capabilities

The reference typed provider accepts only `EffectClass.PURE`.
Effectful typed components must implement the existing canonical
`DurablePreparedCapabilitySession` contract and therefore remain subject to the
prepared-effect journal, exactly-once/reconciliation semantics and recovery
authority. There is no typed direct-execution escape hatch.

## Project authoring

A new paper may define arbitrary request/result schema ids and carrier classes
without editing a Platform enum, model registry, endpoint registry or global
component catalogue. Client code calls `make_typed_capability_request`, invokes
the ordinary capability port, then calls `decode_typed_capability_result` with
its expected descriptor, codec and provider identity.

## Out-of-process conformance

The canonical session contract is transport-neutral. Conformance tests execute
the same arbitrary typed capability once with the local functional provider and
once in a real Windows `spawn` child process over a content-addressed file byte
transport. The two implementations produce the same canonical request digest,
provider identity, participant generation, typed output and full
`CapabilityResult.digest()`.

The subprocess wire encoding in that test is test-proxy plumbing only; it is not
a second Platform serialization authority. Process creation/lifecycle remains
outside Participant, while the provider on either side still satisfies the same
`CapabilityExportSession` semantics.
