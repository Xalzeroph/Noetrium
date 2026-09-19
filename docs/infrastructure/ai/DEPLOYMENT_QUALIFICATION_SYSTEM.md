# Deployment Qualification System

This document is the upstream contract for automatic qualification of model-serving deployments. It is owned by the generic `model/qualification` system and does not select a project model, backend, machine, or experiment.

## Purpose

A package that installs is not necessarily a serving stack that can import native extensions, use the requested accelerators, load the selected artifact, satisfy the requested parallelism, or become a correct live endpoint.

The platform therefore separates qualification into evidence-producing stages:

```text
read-only host/runtime observation
  -> normalized capability closure
  -> evidence-backed candidate resolution
  -> exact frozen materialization
  -> bounded pre-start runtime checks
  -> live serving qualification
  -> qualified deployment closure
```

Every stage is fail-closed. A later stage consumes the frozen identity/evidence produced by the previous stage rather than silently re-resolving a different stack.
## Capability closure

Qualification records deployment-relevant facts or explicitly records that a fact is unavailable. At minimum the typed closure covers:

- host OS, kernel, libc, CPU, RAM, cgroup/container identity;
- accelerator UUID, architecture, memory, PCI/topology, driver/runtime capability;
- multi-device fabric and collective-library identity where applicable;
- target Python ABI, package manager, installed runtime/native-library facts;
- model artifact revision/digest, configuration, shard completeness, dtype/context metadata;
- storage capacity/permissions and declared network/index evidence;
- candidate backend package artifacts, hashes, metadata, requirements, and compatible binary tags.

The controller operating system and the target runtime operating system are separate path domains. Paths embedded in target-runtime probes are serialized with the target runtime's path grammar; controller-local SSH/config/control paths use controller-native validation.

Model `config.json` is treated as measured qualification evidence, not as a permissive metadata bag. Parsed roots must be JSON objects, and observed model type, architecture list, dtype, and context length retain their JSON types; malformed values fail closed instead of being coerced through `str()`/`int()` and marked captured.

The target-Python capability probe follows the same rule: its subprocess JSON has an exact field set and exact string/list/null types. Malformed capability payloads become explicit probe errors, and candidates carrying those errors are rejected rather than qualified from partially reconstructed defaults.

Observation is read-only. It must not download large payloads, install packages, alter GPU state, or mutate the selected environment merely to decide whether a candidate is plausible.
## Resolution and materialization

The resolver is pure over the observed closure and requested quality contract. Its output freezes accepted/rejected candidates, reasons, package identities, source indexes, compatible artifacts, parallelism, and evidence references.

Materialization consumes only the persisted frozen plan. Dependency discovery is not delegated back to an installer. When a complete dependency closure has been observed, exact packages are installed without permitting the package manager to silently select a different transitive graph or source distribution.

A successful installation receipt is not a runtime certificate. Post-materialization verification must separately prove imports, native-library loading, accelerator visibility, device count, parallelism constraints, model configuration compatibility, and package consistency.

Failures persist typed receipts and preserve the original root exception. Qualification never repairs a failure by silently reducing precision/context, changing model revision, switching backend, or reducing the requested quality contract.
## Live qualification

Live readiness is owned by model serving. A qualified live deployment binds:

- frozen model-stack and qualification-plan digests;
- materialization and pre-start receipts;
- exact process/container/runtime generation;
- actual accelerator placement;
- endpoint route generation;
- bounded health/readiness observations;
- role-specific canary evidence where roles are declared.

The resulting qualified deployment closure is an input to downstream admission policy. The upstream platform does not decide whether a particular project may make a scientific claim.

## Operator surface

The management CLI exposes qualification through the generic deployment namespace. A typical downstream call supplies model identity/path, a registered target environment or explicit interpreter, candidate backend identifiers, and requested parallelism. Concrete backend names, model IDs, machine IDs, and quality thresholds are downstream configuration.

`--summary`-style views may abbreviate diagnostics, but the immutable full plan/evidence remains the authority. A summary never replaces a qualification record.
## Reproducibility invariants

- exact revisions/digests are identities; mutable labels are observations only;
- target-environment facts constrain resolution and cannot be ignored because a newer package exists;
- binary/native compatibility must be proven from recorded evidence;
- requested parallelism must satisfy model-architecture and runtime constraints before launch;
- package/application/runtime/live-readiness evidence are separate stages;
- a failed candidate remains failed evidence rather than becoming an implicit fallback;
- qualification records are checksummed and immutable once referenced by a deployment generation.

## Repository boundary

The upstream stores qualification contracts, resolvers, providers, evidence schemas, and generic operator documentation. Concrete deployment investigations, machine observations, chosen model stacks, benchmark results, and project qualification receipts belong to the downstream repository or its external evidence store.

This separation allows the same qualification system to support different models, runtimes, accelerators, and research projects without making any one of them part of the platform identity.

## Persisted qualification schema integrity

The application and runtime qualification stores use checksummed documents, but checksum verification is only the outer integrity layer. After checksum validation, every receipt is decoded against an exact field set and exact scalar/array/object types.

A checksum-valid receipt is rejected when fields are missing or added, a return code is encoded as a string, a package/command/check has the wrong shape, a list contains `null`, or any other coercion would be required. This prevents durable qualification evidence from being silently normalized into a different typed fact.

This strictness applies to platform-owned persisted receipts. It does not prohibit explicit parsing at external process/protocol boundaries, where the source contract itself is textual.