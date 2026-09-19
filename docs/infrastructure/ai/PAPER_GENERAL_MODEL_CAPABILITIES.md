# Paper-General Model Capability Contracts

ROLE04 model authoring no longer assumes that every scientific model call is text completion.
The public `ModelCapabilityRequirement` carries one semantic `capability_id` plus exact input/output schema identities.
Generation and structured generation retain prompt-generation, prompt, tool-schema, and model-visible request provenance.
Non-generation requirements must not invent prompt identity merely to fit the generation API.

The first concrete typed families are:

- generation through the existing small `ProjectModelClientPort.complete()` path;
- structured generation through `StructuredGenerationInput` / `StructuredGenerationOutput` plus `QualifiedStructuredGenerationCapabilityProvider`, which reuses the same qualified completion client and adds an injected schema decoder/validator rather than a second Prompt or endpoint authority;
- embedding through `EmbeddingInput` and `EmbeddingOutput`;
- scoring through `ScoringInput` and `ScoringOutput`;
- ranking through `RankingInput` and `RankingOutput`, which preserves explicit ordered rank identity instead of treating ranking as an incidental sort of scores;
- policy inference through `PolicyInferenceInput` and `PolicyInferenceOutput`, which carries a typed normalized action distribution and optional selected action;
- value-style inference through `ValueInferenceInput` and `ValueInferenceOutput`;
- multimodal inference through `MultimodalInferenceInput` / `MultimodalInferenceOutput`, where media and derived outputs are immutable `ContentRef` values rather than inline large bytes or filesystem paths.
- streaming through `ModelCapabilityStreamChunk` / `ModelCapabilityStreamTerminal` and the public streaming client/session/provider protocols; pull-based consumption provides the semantic backpressure boundary while chunk chaining and terminal disposition preserve ordered provenance.

Embedding vectors, scores, ranking scores, policy probabilities, values, and auxiliary scalars are finite numeric tuples/values. NaN and infinities fail closed. Ranking order and policy normalization are semantic invariants rather than provider conventions.
The typed capability path does not use `object`, `Any`, text fields, or a free-form plugin payload as scientific output authority.
## Binding and provider semantics

`ProjectModelBinding` now binds capability and schema identity in addition to provider/model/deployment qualification provenance.
Prompt identity is mandatory only for generation capabilities and forbidden for non-generation bindings.
The existing `QualifiedModelProjectProvider` remains explicitly generation-only and returns a typed unsupported-protocol diagnostic for other capability families instead of routing them through `complete()`.

Ranking and policy inference use the same `ModelCapabilityInvocation` / `ModelCapabilityResponse` provenance envelope as embedding, scoring, and value inference. They bind semantic schema ids directly and must not carry fabricated Prompt identity or be routed through the generation-only `complete()` client.

Structured generation intentionally keeps generation Prompt provenance. Its typed input binds the existing `ModelRequestEnvelope`, frozen visible body, and exact requested output-schema SHA-256. The adapter delegates the visible request to the already-qualified generation client, then invokes a `StructuredGenerationDecoderPort`; the typed output binds the validated document, exact schema digest, model revision, and underlying completion response digest.

Multimodal inference reuses the existing content-addressed request vocabulary. `MultimodalContent` adds only a semantic role around a `ContentRef`; it does not own storage, transport, upload, or path identity. The capability input/output digest therefore follows immutable content identity and can move across storage providers without changing scientific semantics.

`FunctionalModelCapabilityProvider` is a provider-author reference implementation, not a new qualification authority.
It receives an exact `ProjectModelBinding` factory, validates requirement/binding/capability/schema identity, and executes a strongly typed handler.
It cannot mint deployment generation, model qualification, runtime canary, or provider readiness facts.

Streaming is a semantic sequence contract, not a transport API. Each chunk binds request/binding identity, a contiguous sequence index, the previous chunk digest, schema identity and typed payload digest. A completed terminal binds the ordered chunk digest sequence plus the final typed response; cancelled/failed terminals cannot fabricate a final response and require an explicit reason. `next_chunk()` is intentionally pull-based so consumers control demand. HTTP/SSE/socket/async I/O, buffering and worker supervision remain below this ROLE04 contract.

This keeps provider/deployment substitution below the project method while preserving exact request/output provenance. Multimodal and streaming providers may consume verified content references where large content identity is required, but must not create a second storage/content authority.