# Minecraft Docker runtime

The base platform image remains provider-neutral and lightweight. The base image is built from the formally qualified Noetrium wheel. Minecraft is a reusable upstream environment profile layered on that immutable base image.

## Images

`deploy/Dockerfile` defines the evidence-bound generic Python platform image. It is built only from a prepared formal container context; `deploy/compose.yaml` consumes the resulting image and does not rebuild Platform source.

`deploy/environments/minecraft/Dockerfile` consumes `PLATFORM_BASE_IMAGE` and adds Java 21, Node 22, and the lockfile-pinned Mineflayer bridge runtime. It copies no Noetrium source tree, benchmark manifest, paper method, checkpoint, or downstream project code.

`deploy/environments/catalog.json` is the environment-profile authority. `deploy/compose.minecraft.yaml` remains only as a compatibility overlay and points to the canonical Minecraft environment Dockerfile.

## Compose overlay

Build the exact qualified base image first, then use the environment overlay:

    export PLATFORM_IMAGE="noetrium:<exact-source-sha>"
    docker compose -f deploy/compose.yaml -f deploy/environments/minecraft/compose.yaml build platform-runtime
    docker compose -f deploy/compose.yaml -f deploy/environments/minecraft/compose.yaml run --rm platform-runtime environment-doctor minecraft

Mutable Minecraft provider state is bound below `${PLATFORM_HOST_DATA_ROOT}/minecraft`; generic platform state remains below `${PLATFORM_HOST_DATA_ROOT}/platform-state`.

The environment profile does not publish a Minecraft TCP port and does not ship a Minecraft server artifact. Downstream scientific deployments own the exact server/world cut, task manifest, benchmark adapter, method, model/checkpoint bindings, metrics, seeds, and claims.

## Reproducibility

Production automation should pin the base image digest, environment image digest, Node version, Java runtime image digest, Minecraft server artifact digest, and downstream world/task identities. Build immutable images once and reuse those exact identities across execution nodes.
