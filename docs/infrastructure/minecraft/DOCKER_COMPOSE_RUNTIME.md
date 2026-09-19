# Minecraft Docker runtime

The base platform image remains provider-neutral and lightweight. Minecraft is shipped upstream as a bundled provider, but its Java/Node runtime is opt-in through `deploy/Dockerfile.minecraft` and `deploy/compose.minecraft.yaml`.

This separation keeps ordinary platform users from paying the cost of Java, Node and Mineflayer while preserving a reproducible first-party Minecraft runtime.

## Images

`deploy/Dockerfile` builds the generic Python platform image.

`deploy/Dockerfile.minecraft` builds the Minecraft-capable image with Python 3.12, Java 21, Node 22 and the lockfile-pinned Mineflayer bridge. It contains no downstream project code or benchmark manifests.

## Compose overlay

Use both Compose files when Minecraft capability is required:

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.minecraft.yaml build platform-runtime
docker compose -f deploy/compose.yaml -f deploy/compose.minecraft.yaml run --rm platform-runtime minecraft-doctor
```

Mutable Minecraft state is bound below `${PLATFORM_HOST_DATA_ROOT}/minecraft`; generic platform state remains below `${PLATFORM_HOST_DATA_ROOT}/platform-state`.

The overlay does not publish a Minecraft TCP port by default. A downstream deployment may add a port mapping when external clients genuinely require one.

## Reproducibility

Production automation should pin the platform release/source identity, Node version, Minecraft server artifact digest and Java/runtime evidence. Build an immutable image once and reuse that exact image identity across execution nodes rather than rebuilding under the same tag.

Project-specific task manifests, scenario choices and scientific run configuration are downstream inputs and must not be baked into the upstream image.
