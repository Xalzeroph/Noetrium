# Minecraft Docker runtime

The base platform image remains provider-neutral and lightweight. The base image is built from the formally qualified Noetrium wheel. Minecraft is a reusable upstream environment profile layered on that immutable base image.

## Images

`deploy/Dockerfile` defines the evidence-bound generic Python platform image. It is built only from a prepared formal container context; `deploy/compose.yaml` consumes the resulting image and does not rebuild Platform source.

`deploy/environments/minecraft/Dockerfile` consumes `PLATFORM_BASE_IMAGE` and adds Java 21, Node 22, and the lockfile-pinned Mineflayer bridge runtime. Java is a registry-declared image build input and is resolved to a concrete image digest. Node version and the expected Linux x64 archive SHA-256 are registry-declared parameter inputs; the Dockerfile verifies the downloaded archive directly against that fixed digest before extraction. It copies no Noetrium source tree, benchmark manifest, paper method, checkpoint, or downstream project code.

`deploy/environments/catalog.json` is the environment-profile authority. There is no legacy Minecraft compose alias; callers use the canonical environment profile path directly.

## Compose overlay

Use the canonical environment image entrypoint. It builds the exact evidence-bound base only when needed, reuses exact-SHA images when available, runs the Minecraft doctor, and writes the provenance receipt:

    ./deploy/build-environments.sh build --profiles minecraft

Use `--rebuild` only when intentionally invalidating the exact build-input cache. Deployment mirrors or intentional parameter substitutions use the generic `--build-input ENV=value` surface; there are no Minecraft-specific Java/Node switches in the central builder. The Compose overlay remains an implementation detail consumed by the build entrypoint, not the downstream operational interface.

Mutable Minecraft provider state is bound below the required per-instance `PLATFORM_ENVIRONMENT_INSTANCE_ROOT`; generic platform runtime state is bound below the required per-instance `PLATFORM_RUNTIME_STATE_ROOT`. The Compose overlay fails closed when either writable root is missing, so two papers cannot silently share world or platform state.

The environment profile does not publish a Minecraft TCP port and does not ship a Minecraft server artifact. Downstream scientific deployments own the exact server/world cut, task manifest, benchmark adapter, method, model/checkpoint bindings, metrics, seeds, and claims.

## Reproducibility

Production automation distinguishes recipe, build and runtime identities. `profile_id + profile_revision` identifies the immutable profile recipe; `build_input_digest` includes the exact base image, Java runtime image digest, Node version and pinned Node archive hash; `runtime_identity_digest` identifies the final image content. The environment image carries OCI labels for profile id, category id, profile revision and build-input digest, and the builder verifies all of them before accepting reuse. Downstream deployments separately pin the Minecraft server artifact, world/task identities and other scientific inputs.
