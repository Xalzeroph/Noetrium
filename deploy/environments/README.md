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

Existing executions remain pinned to the exact `profile_id + profile_revision` recorded by `EnvironmentInstance`.

## Lifecycle

Profiles have exactly three lifecycle states:

- `active`: eligible for new bindings;
- `draining`: no default new binding; already pinned executions may finish or resume;
- `retired`: historical/recovery-only; explicit `--allow-retired` is required to materialize it.

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

Explicit historical recovery is possible:

```bash
./deploy/build-environments.sh build --profiles minecraft-r1 --allow-retired
```

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

Build receipts include source SHA, wheel SHA-256, distribution-evidence SHA-256, profile id, category, profile lifecycle, profile revision digest and concrete image identity.

An exact cached base is re-verified before reuse. Profile images are tagged by both source and profile revision, so changing the profile definition cannot silently reuse an older image.

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
2. add a Dockerfile that extends `PLATFORM_BASE_IMAGE` unless the profile is `base-only`;
3. add a profile-local doctor hook;
4. add a Compose overlay if the profile needs one;
5. run `./deploy/build-environments.sh validate`;
6. build and doctor the new revision.

The registry gate rejects downstream benchmark/paper content in platform-owned images.

## Safe upgrade and retirement

Never overwrite a revision in place.

Create a new profile revision, make it the active default, move the prior revision to draining, and only later mark it retired after no new work can bind it. Existing `EnvironmentInstance` records keep their exact deployment revision.

This gives Noetrium Git-like environment evolution: new executions move forward while old executions remain recoverable and attributable.
