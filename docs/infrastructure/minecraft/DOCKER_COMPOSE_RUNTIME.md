# Minecraft Docker runtime

The base platform image remains provider-neutral and lightweight. The base image is built from the formally qualified Noetrium wheel. Minecraft is a reusable upstream environment profile layered on that immutable base image.

## Images

`deploy/Dockerfile` defines the evidence-bound generic Python platform image. It is built only from a prepared formal container context; `deploy/compose.yaml` consumes the resulting image and does not rebuild Platform source.

`deploy/environments/minecraft/Dockerfile` consumes `PLATFORM_BASE_IMAGE` and adds Java 21, Node 22, and the lockfile-pinned Mineflayer bridge runtime. It copies no Noetrium source tree, benchmark manifest, paper method, checkpoint, or downstream project code.

`deploy/environments/catalog.json` is the environment-profile authority. There is no legacy Minecraft compose alias; callers use the canonical environment profile path directly.

## Compose overlay

Use the canonical environment image entrypoint. It builds the exact evidence-bound base only when needed, reuses exact-SHA images when available, runs the Minecraft doctor, and writes the provenance receipt:

    python scripts/build_environment_images.py build --profiles minecraft

Use `--rebuild` only when intentionally invalidating the exact-SHA cache. The Compose overlay remains an implementation detail consumed by the build entrypoint, not the downstream operational interface.

Mutable Minecraft provider state is bound below `${PLATFORM_HOST_DATA_ROOT}/minecraft`; generic platform state remains below `${PLATFORM_HOST_DATA_ROOT}/platform-state`.

The environment profile does not publish a Minecraft TCP port and does not ship a Minecraft server artifact. Downstream scientific deployments own the exact server/world cut, task manifest, benchmark adapter, method, model/checkpoint bindings, metrics, seeds, and claims.

## Reproducibility

Production automation should pin the base image digest, environment image digest, Node version, Java runtime image digest, Minecraft server artifact digest, and downstream world/task identities. Build immutable images once and reuse those exact identities across execution nodes.
