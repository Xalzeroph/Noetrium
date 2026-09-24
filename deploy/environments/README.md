# Noetrium environment profile registry

Noetrium owns reusable execution prerequisites, not paper or benchmark environments.

The deployment model is:

```text
L0 host substrate
   Docker / Compose / NVIDIA runtime / filesystem / network
        |
L1 evidence-bound Noetrium base
   exact qualified wheel + release evidence
        |
L2 environment capability profile
   web / minecraft / gui / embodied / software / text-like categories
        |
L3 immutable workload assets
   content-addressed datasets / VM bases / world bases / repository objects
        |
L4 per-execution writable overlay
   workspace / tmp / runtime state / browser profile / world state / secrets
        |
L5 immutable research evidence
   artifacts / trajectories / metrics / checkpoints / Machine Journal receipts
```

The central rule is:

> Share immutable content. Isolate every mutable execution state.

## Registry authority

`deploy/environments/catalog.json` is the environment-profile registry authority.

The registry is dynamic. The build control plane does not contain a hard-coded set of profile names. Adding a new category or a new revision requires only a registry row plus that profile's own image recipe, Compose overlay when needed, and doctor hook.

Each row has two different identities:

- `category_id`: the stable capability family used by research requirements, such as `web` or `minecraft`;
- `profile_id`: one concrete deployable profile revision line.

A profile revision digest is derived from the immutable profile definition. Administrative lifecycle fields are excluded from that digest, so moving a revision from active to draining or retired does not change the software environment identity.

This allows revisions to coexist:

```text
category: minecraft
  minecraft-r1  retired   revision=A...
  minecraft-r2  draining  revision=B...
  minecraft-r3  active    revision=C...  <- default for new executions
```

Environment deployment uses three distinct identities:

- `profile_revision`: the logical recipe identity derived from the profile definition and recipe bytes;
- `build_input_digest`: the cache/build identity derived from the recipe plus the exact base runtime identity and any profile-specific upstream runtime inputs such as Java and Node version;
- `runtime_identity_digest`: the final content identity of the built image.

Existing executions record the logical profile cut and concrete `runtime_identity_digest`. Warm-instance reuse requires the same profile revision and runtime identity, while image-cache reuse is namespaced by `build_input_digest`. A recipe can therefore stay logically unchanged without allowing a changed base image, Java image, or Node version to masquerade as the same cached build.

## Lifecycle

Profiles have exactly three lifecycle states:

- `active`: eligible for new bindings;
- `draining`: no default new binding; only an execution with an existing durable pin may resume it;
- `retired`: historical-recovery-only; runtime use requires historical-recovery intent backed by a durable pin, and explicit `--allow-retired` is required to materialize its image.

Retirement is the logical delete operation. A retired registry row is retained so historical experiments keep a reproducible environment identity.

Physical cache/image deletion is a separate operation. A revision is GC-eligible only when there is no active or resumable execution referencing it and no retained evidence depends on it.

## Sharing and isolation

Safe sharing is limited to immutable or content-addressed objects:

- Noetrium base image layers;
- environment profile image layers;
- model and tokenizer blobs;
- immutable benchmark assets;
- VM/world/base snapshots;
- repository object caches;
- content-addressed dependency caches.

Per-execution writable state is never shared:

- workspace;
- `/tmp`;
- runtime/world/application state;
- browser profiles and cookies;
- secrets and environment-local credentials;
- process namespace;
- network namespace;
- ports;
- mutable databases.

Compose runtime state therefore uses an instance-scoped root. `PLATFORM_ENVIRONMENT_INSTANCE_ROOT` identifies environment-owned writable state and `PLATFORM_RUNTIME_STATE_ROOT` identifies platform runtime state for that execution instance.

A reusable warm instance can return to a pool only after its overlay is destroyed or a provider produces an explicit cleanliness proof. A dirty or uncertain instance must be destroyed, never opportunistically reused.

The rule is executable in the Environment catalog. Instance lifecycle is:

```text
CLEAN --bind/checkout--> IN_USE --release without proof--> DIRTY
  ^                         |
  |                         +--release with exact proof--> CLEAN
  |
  +---------------- generation-fenced cleanliness proof
DIRTY --exact reset/overlay-destroy proof--> CLEAN
CLEAN/DIRTY/IN_USE(unbound abort) --destroy--> DESTROYED
```

Each checkout increments `EnvironmentInstance.generation`. `EnvironmentCleanlinessProof` binds the instance id, immutable profile revision, concrete `runtime_identity_digest`, exact generation, proof kind and proof digest. A proof from generation N cannot certify generation N+1, and a proof for one concrete runtime cannot certify another. `reusable_instances()` returns only CLEAN instances matching the requested profile revision and runtime identity.

The same authority exposes two GC cuts. `runtime_references()` / `assess_runtime_gc()` operate on one exact `profile_id + profile_revision + runtime_identity_digest` and are the authority for deleting a concrete image/runtime object. `profile_references()` / `assess_profile_gc()` aggregate every concrete runtime produced from the recipe revision and are the authority for deleting the whole logical profile revision. This distinction matters when the same recipe has multiple concrete outputs across hosts or rebuilds: one exact runtime may be collectible while another remains pinned, so exact-runtime GC must not be inferred from profile-level identity alone.

Both assessments fail closed. Local eligibility requires zero live bindings and every matching catalog instance to be DESTROYED. Final GC additionally requires Execution and Evidence to provide complete closure results. An unknown or missing external reference set is blocking; an explicit empty tuple means that authority has proven closure. Environment never claims those external truths itself.

## Profile-local doctors

The base entrypoint does not contain a switch statement for known environment types.

Each image profile installs its own executable doctor hook at:

```text
/usr/local/lib/noetrium/environment-doctor.d/<category>
```

The generic entrypoint performs the base Noetrium qualification first and then executes the profile hook. This removes a central edit point: a new environment category does not require changing `container-entrypoint.sh`.

## Host contract

The host contract remains Docker + Docker Compose and access to the Docker daemon. GPU nodes additionally need the NVIDIA container runtime required by their provider.

Host Python is not part of the deployment contract. Qualification and image orchestration run in the disposable bootstrap image:

```bash
./deploy/build-environments.sh list
./deploy/build-environments.sh show minecraft
./deploy/build-environments.sh validate
./deploy/build-environments.sh build
```

With no `--profiles`, build selects exactly one active default revision for every registered category.

Profile-specific immutable build inputs are declared by the registry, not hard-coded in the builder. An image input declares its canonical image selector and environment variable; a parameter input declares its canonical default and environment variable. The builder resolves image inputs to concrete content digests, includes those digests and parameter values in `build_input_digest`, injects the values into the profile Compose build, and records the complete resolved input set in the build receipt.

Deployment-specific mirrors or parameter substitutions use the generic override surface:

```bash
./deploy/build-environments.sh build --profiles minecraft \
  --build-input JAVA_RUNTIME_IMAGE=registry.example/java/runtime \
  --build-input NODE_VERSION=22.22.2
```

An override that is not declared by one of the selected profiles fails closed. Adding a new profile-specific runtime input therefore changes only the registry row and that profile's recipe/Compose wiring; the central builder remains unchanged.

Explicit recovery is separated by lifecycle:

```bash
# Resume an execution already pinned to a draining revision.
./deploy/build-environments.sh build --profiles minecraft-r2 --allow-draining

# Historical recovery of a fully retired revision.
./deploy/build-environments.sh build --profiles minecraft-r1 --allow-retired
```

Passing an old profile id through `--profiles` without the matching recovery-intent flag fails closed. This prevents draining or retired revisions from silently receiving new work.

The bootstrap preserves the checkout read-only and gives write access only to its dedicated build/runtime root.

## Image identity and provenance

The immutable base is built from a formally qualified Noetrium wheel and release evidence, not directly from a mutable checkout.

```text
release source
  -> qualified wheel + distribution evidence
  -> exact container context
  -> evidence-bound base image
  -> provenance verification
  -> environment profile image
  -> profile doctor
  -> build receipt
```

Build receipts include source SHA, wheel SHA-256, distribution-evidence SHA-256, exact upstream runtime-source identities, profile id, category, profile lifecycle, profile revision digest, `build_input_digest`, Docker image metadata, and the final normalized `runtime_identity_digest`.

The base cache key includes the exact Python runtime source identity, and the base image carries that digest as an OCI label verified by the formal container verifier. Profile cache keys use the complete `build_input_digest`; profile images carry the same digest as an OCI label. Profile-specific inputs are generic registry data. For the current Minecraft profile this includes the exact Java runtime image identity, Node version, and the pinned SHA-256 of the Node Linux x64 archive in addition to the base image.

Registry mirrors are deployment configuration. Canonical runtime identities remain separately recorded from the actual source registry image.

## Current categories

The current registry ships the following active categories, but this set is not encoded in builder logic:

| Category | Shared capability layer | Downstream-owned examples |
| --- | --- | --- |
| `text_world` | qualified Python/Noetrium base | corpora, benchmark runtimes, task semantics |
| `web` | Chromium + driver | sites, site state, benchmark tasks |
| `minecraft` | Java, Node, Mineflayer provider prerequisites | server/world/task/benchmark assets |
| `gui` | Xvfb, Openbox, xdotool, screenshot stack | VM images, applications, task state |
| `embodied` | EGL/OpenGL/OSMesa/headless display | simulator benchmarks, robot tasks, scenes |
| `software` | compiler/build/SSH tools | repositories, patches, benchmark images |

A downstream paper must never force a paper-specific layer into this registry. Papers bind reusable categories and materialize their own immutable assets and private execution overlay.

## Adding a profile

To add a profile without changing central platform code:

1. add a registry row with `profile_id`, `category_id`, lifecycle and isolation policy;
2. declare any profile-specific immutable image/parameter inputs under `build_inputs`; do not add profile-name conditionals to the builder;
3. add a Dockerfile that extends `PLATFORM_BASE_IMAGE` unless the profile is `base-only`;
4. add a profile-local doctor hook;
5. add a Compose overlay if the profile needs one and wire every declared build-input environment variable through it;
6. run `./deploy/build-environments.sh validate`;
7. build and doctor the new revision.

The registry gate rejects downstream benchmark/paper content in platform-owned images.

## Safe upgrade and retirement

Never overwrite a revision in place.

Create a new profile revision, make it the active default, move the prior revision to draining, and only later mark it retired after no new work can bind it and no instance is still in use. Existing `EnvironmentInstance` records keep both their exact deployment revision and concrete runtime identity.

This gives Noetrium Git-like environment evolution: new executions move forward while old executions remain recoverable and attributable.
