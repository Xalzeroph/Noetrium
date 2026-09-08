# New Project Agent & Model Surface

This document defines the ROLE04-owned downstream seam used by the New Project Experience (NPE). It is a projection over existing Participant and Model authorities; it does not create a second project runtime, model registry, process manager, or qualification system.

## Common project imports

Ordinary downstream project code should begin with only:

```python
from noetrium.contracts.agent import (
    AgentIdentity,
    AgentSession,
    AgentTurnRequest,
    AgentTurnResult,
)
from noetrium.contracts.participant import AgentProjectDefinition
from noetrium.contracts.model import ModelCapabilityRequirement
```

A project can define Agent behavior with `AgentSession`, declare the exact Agent identity through `AgentProjectDefinition`, and state model requirements through `ModelCapabilityRequirement` without importing Participant runtime/catalog packages or Model serving providers.

The common path intentionally does not contain a serving URL, process PID, process-generation token, resource allocator, or session-runtime constructor.
## Participant/Agent projection

`AgentProjectDefinition` converts the public Agent identity into a `ParticipantRequirement`. The requirement binds:

- project role;
- exact Participant implementation identity;
- immutable configuration digest;
- required capability names.

`ProjectParticipantProviderPort` is the provider-author conformance seam. A provider may choose a local, server, container, or other Participant session runtime, but it must return a `ProjectParticipantBinding` whose role, implementation, configuration, requirement digest, and provider-profile digest remain exact.

The reference `RuntimeParticipantProjectProvider` lives under `noetrium_platform.capabilities.participant.providers` for provider/composition authors. Common project code does not import it. It adapts the existing Participant binding resolver and detects runtime binding drift before publication.

Provider switching is therefore a composition decision: changing the selected session runtime does not change project Agent identity or capability requirements.
## Model requirement and qualified binding

`ModelCapabilityRequirement` is project-owned source/configuration identity. It binds:

- logical model role;
- exact prompt generation, prompt ID, and prompt digest;
- required provider capabilities;
- minimum context length;
- optional exact tool-schema digest.

`ProjectModelProviderPort` is the provider-author conformance seam. Its `bind()` result exposes a `ProjectModelClientPort`; the project-visible `ProjectModelBinding` contains exact model, deployment-generation, stack, qualification-certificate, runtime-qualification, host, prompt, provider-profile, and runtime-canary evidence identities.

It deliberately does **not** expose serving URLs, HTTP paths, process IDs, process start markers, or process-manager objects. Those remain inside the Model provider/qualification implementation.
## Exact request provenance

`ProjectModelRequest` carries the existing `ModelRequestEnvelope` rather than inventing a second request record. Before dispatch, the reference adapter verifies that the envelope agrees with the bound requirement and qualified client on:

- role and exact model identity;
- prompt generation, prompt ID, and prompt digest;
- required tool-schema digest;
- deployment ID and deployment generation.

The request body is recursively frozen at construction and receives its own request digest. Before dispatch, the reference adapter also calls the existing `ModelRequestRecorderPort.verify_visible_request()` authority, so a valid envelope cannot be rebound to different actual model-visible bytes.

The low-level endpoint route and response stay inside the provider. After dispatch, request ID and deployment ID must still match the bound envelope/deployment. `ProjectModelResponse` then projects only request/binding/response digests, text, finish reason, and token counts; it does not expose the endpoint response object.

This preserves existing content-addressed model-visible request authority while allowing a provider/deployment swap to remain a composition change when the same public requirement is satisfied.
## Doctor diagnostics and provider conformance

Both provider ports expose `diagnose(requirement)` and return typed immutable diagnostics. Diagnostic codes distinguish missing capability, insufficient model context, unavailable qualification/runtime, and provenance drift. Provider exception text is not copied into project-facing messages, preventing accidental exposure of credentials, routes, or host-local paths.

A provider-facing conformance implementation must:

1. accept only typed ROLE04 requirements;
2. fail closed when a required capability cannot be met;
3. preserve requirement identity across resolution;
4. preserve qualified model/Participant provenance;
5. never synthesize qualification or runtime truth from project assertions;
6. expose typed diagnostics before the common project path attempts work.

`QualifiedModelProjectProvider` and `RuntimeParticipantProjectProvider` are reference adapters proving this extension seam. They are composition/provider-author examples, not imports required by ordinary project code.
## ROLE06 handoff

ROLE06 may build the canonical Python facade, project scaffold, provider templates, doctor, and CLI over the following stable ROLE04 surfaces:

- `noetrium.contracts.agent` and `noetrium.contracts.participant`: Agent behavior/identity, Participant requirements/bindings, typed diagnostics, provider port;
- `noetrium.contracts.model`: model capability requirement, qualified project binding/client, exact project request/response, typed diagnostics, provider port.

ROLE06 must not recreate Participant runtime selection, serving endpoint construction, qualification decisions, request provenance, or model/Participant truth inside its facade. Provider templates may implement the public provider ports; common generated project code should depend only on the public API packages above.

The focused conformance gate is `tests/test_typed_project_agent_model_npe_v1.py`. It verifies public-only project imports, Agent behavior definition, provider substitution, exact prompt/tool/model provenance, durable body/envelope equality, fail-closed response provenance, typed doctor failures, no route/process leakage, and provider-author structural conformance.
