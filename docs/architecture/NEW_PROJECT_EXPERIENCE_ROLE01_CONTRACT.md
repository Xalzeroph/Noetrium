# ROLE 01 New Project Experience Contract

This document is the ROLE 01 producer contract for Playbook v3.2 ?37.3. It is additive to the existing architecture, SourceIndex, registry, Scope and Portfolio authorities.

## Authority

There is no new Project top-level system. Project identity and manifest truth are owned by the existing Portfolio/Scope path. Capability composition remains Governance architecture truth. A downstream project is represented as a project composition subject and must never be registered as a Platform system merely to bind capabilities.

## Public project surface

The canonical common-path module is `noetrium_platform.foundation.portfolio.api`. `ProjectIdentity` identifies one versioned project. `ProjectManifest` groups project metadata, explicit capability binding inputs, project-owned method requirements, content-addressed configuration references, and study references.

The wire codec is strict and digest-bound. `encode_project_manifest()` emits canonical UTF-8 JSON for schema `noetrium.project-manifest.v2`; `decode_project_manifest_bytes()` rejects duplicate keys and invalid/non-finite JSON before typed decoding; `decode_project_manifest_document()` rejects unknown fields and verifies `semantic_digest` against the canonical semantic payload.

`template_revision` is a digest-bound product input, not a Portfolio compatibility authority. ROLE 01 validates only that the recorded revision is canonical non-empty text and preserves it exactly; ROLE 06 owns scaffold/template revision values and decides whether a recorded revision is supported by the installed product. Unknown future template revisions therefore remain decodable by Portfolio and must be accepted or rejected by the ROLE 06 product layer.

The leaf `noetrium_platform.foundation.portfolio.project.api` re-exports the same classes/functions. It is not an independent authority.

## Composition boundary

`ProjectCapabilityRequirement` is the manifest-level binding input. It identifies capability namespace/name/major version, interface digest, cardinality and optionality without naming a concrete provider. The advanced public composition contracts (`CompositionSubject`, `CompositionIdentity`, `CapabilityRequirement`, `CapabilityCompositionPlannerPort`, etc.) are exported by `noetrium_platform.foundation.governance.architecture.api` for Platform/advanced consumer composition roots.

Common generated projects do not import Governance runtime/provider modules and do not perform ambient registry lookup.

## Dependency policy

`audit_downstream_project_imports()` is the machine-verifiable downstream policy. Top-level `<system>.api` imports are common-path APIs; deeper explicit `...api` imports are provider/advanced APIs; all other `noetrium_platform.*` imports are private implementation dependencies and block conformance. Vendoring `noetrium_platform/` into a downstream root also blocks conformance.

## ROLE 06 handoff

ROLE 06 scaffold/create/doctor should use:

- `ProjectIdentity`, `ProjectManifest`, `ProjectCapabilityRequirement`, `ProjectConfigurationReference`, `ProjectMethodRequirement`;
- `encode_project_manifest`, `decode_project_manifest_bytes`, `decode_project_manifest_document`;
- `audit_downstream_project_imports` for generated-project/private-import checks;
- `noetrium_platform.foundation.governance.architecture.api` only inside the Platform composition/advanced path when a binding plan is required.

ROLE 06 must not copy the wire schema, semantic digest implementation, project-id rules, or import classifier into Product code. ROLE 06 does own template/scaffold revision constants and compatibility policy; it must treat `template_revision` from the ROLE 01 manifest as an input to that policy rather than asking Portfolio to decide product compatibility. Missing domain capabilities remain CSRs to the owner roles.

## Acceptance

ROLE 01 acceptance requires focused manifest/import/composition tests, canonical TEST_SYSTEM classification, public-contract weak count zero, Algorithm Gate closure for ROLE01-owned blockers, Architecture/Silent/No-Degradation gates, exact Windows regression, a clean/pushed exact SHA, and ROLE 00 re-binding any exact-SHA architecture migration approval invalidated by the final commit.


## Method implementation identity

Project Manifest v2 requires every `ProjectMethodRequirement` to carry a
content-addressed `implementation_digest`. This digest identifies the exact
participant implementation selected for the scientific treatment; it is not a
Git repository locator and it is not method-source provenance.

Compilation must prove that the resolved participant implementation digest is
identical to the project-owned method requirement. A mismatch is a hard error.
The resulting method-implementation digest is part of the compiled research
plan and checkpoint-compatibility identity, so a checkpoint can never be
resumed across a method implementation change.

External paper/source relationships belong exclusively to
`noetrium_platform.research.provenance.MethodSourceRegistry`. Study design
does not carry repository URLs, commits, or source-lane classifications.
