# Open Multimodal Method Contract

Noetrium treats multimodality as an open method boundary, not as one
vendor-specific image-plus-text format. A downstream paper may define any
finite collection of input or output modalities, any ordering and temporal
relationship, and any method-owned schema or parameters.

## Contract layers

| Layer | Noetrium contract | Authority |
| --- | --- | --- |
| Method | `MultimodalMethodSpec` | Downstream method |
| Content | `ContentRef` in `MultimodalPart` | Content-addressed store |
| Invocation | `MultimodalRequest` / `MultimodalResponse` | Model capability boundary |
| Encoding | `MultimodalRequestCodecPort` | Provider or model adapter |
| Agent view | `AgentMultimodalObservationProjector` | Agent runtime assembler |

`modality_id` is a non-empty string rather than an enum. Examples such as
`image/rgb`, `audio/wav`, `minecraft/voxel-observation`,
`application/x-point-cloud`, token lattices, action distributions, and
learned latent tensors are all equally valid. Noetrium does not interpret
these values.

## Method-owned semantics

`MultimodalMethodSpec` carries method and revision identity, input/output
schema identifiers, open modality declarations, and frozen JSON parameters.
The schemas and parameters belong to the paper method. They can describe
early fusion, late fusion, cross-attention, co-training, retrieval, world
models, recurrent windows, action distributions, or a new method without
changing Noetrium.

Each `MultimodalPart` carries a role and content reference plus optional
encoding, part identity, sequence position, time interval, coordinate frame,
metadata, and source references. This makes repeated, asynchronous, spatial,
or derived modalities representable without adding special fields for a
particular paper.

## Provider boundary

Noetrium stores and verifies content references; it does not serialize them
into an OpenAI, Qwen, Mindcraft, or other vendor request shape. A provider
implements `MultimodalRequestCodecPort` and decides how its selected method
consumes the referenced bytes and metadata. The provider may reject a method
or modality it cannot serve, but it must not silently reinterpret it.

The request and response also implement the generic model capability input
and output protocols. They can therefore travel through
`ModelCapabilityInvocation` and the existing functional or project model
provider seams, preserving request, binding, and response digests.

## Agent assembly

Environment adapters publish content-addressed parts. The agent runtime may
use `AgentMultimodalObservationProjector` to attach those parts to an
`AgentObservation`. The projector preserves part order, provenance, timing,
coordinate frame, and content identity; it does not perform vision,
audio, language, fusion, or policy inference. Those operations remain in the
method/provider selected by the downstream project.

## Downstream usage rule

1. Declare the paper method with `MultimodalMethodSpec`.
2. Put every raw or derived payload in the existing content store.
3. Create `MultimodalPart` values using the resulting `ContentRef`s.
4. Build a `MultimodalRequest` and invoke it through the generic model
   capability boundary.
5. Implement only the provider codec and method logic that the paper needs.
6. Project observations with the upstream agent assembler when an agent view
   is required.

The older `MultimodalInferenceInput` and `MultimodalInferenceOutput` remain
available for compatibility. New downstream work should use the open
method/part/request/response contract above.
