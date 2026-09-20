# Noetrium environment container profiles

Noetrium owns reusable execution-environment prerequisites, not scientific environments.

The immutable base image is built from a formally qualified Noetrium wheel and its release evidence. Environment profiles consume that base image and add only generic operating-system/runtime dependencies required by one canonical environment category.

## Boundary

Upstream owns:

- the evidence-bound Noetrium base image;
- generic Java/Node/Mineflayer prerequisites for the Minecraft provider;
- generic EGL/OpenGL/OSMesa/headless-display prerequisites for embodied providers;
- generic headless desktop tooling for GUI providers;
- generic Chromium runtime for Web providers;
- generic compiler/build/terminal prerequisites for Software providers;
- environment-profile readiness diagnostics.

Downstream research owns benchmark packages/data, task/world/site/repository cuts, paper methods/prompts, model checkpoints/training data, and scientific experiment manifests/seeds/metrics/success predicates/claims.

`deploy/environments/catalog.json` is the deployment-profile authority. A profile must not name or embed a downstream benchmark implementation.

## Base image

The base image is distribution-bound and must not be rebuilt directly from the mutable checkout. Follow `docs/release/DISTRIBUTION_QUALIFICATION.md`:

    GIT_SHA="$(git rev-parse HEAD)"
    python scripts/release_distribution.py /tmp/noetrium-distribution
    python scripts/prepare_container_context.py \
      /tmp/noetrium-distribution /tmp/noetrium-container \
      --expected-source-sha "$GIT_SHA"

Read wheel/evidence digests from the generated release evidence, then build `deploy/Dockerfile` from `/tmp/noetrium-container` and tag it with the exact source revision. Production deployments should prefer an immutable image digest.

`deploy/compose.yaml` consumes an already-qualified `PLATFORM_IMAGE`; it does not build the base image from checkout source.

## Environment profiles

| Profile | Adds | Does not add |
| --- | --- | --- |
| `minecraft` | Java 21, Node 22, lockfile-pinned Mineflayer bridge runtime | Minecraft server/world/task/benchmark |
| `embodied` | EGL, OpenGL, OSMesa, headless X runtime | benchmark simulators, task packages, robot-specific assets |
| `gui` | Xvfb, Openbox, xdotool, screenshot tooling | benchmark VM images, applications, task manifests |
| `web` | Chromium and chromedriver | benchmark websites, application state, task manifests |
| `software` | compiler/build/SSH workspace prerequisites | benchmark images, target repositories, task patches |
| `text_world` | base image only | benchmark runtimes and task corpora |

Build and diagnose one environment profile by composing the base service with one overlay:

    export PLATFORM_IMAGE="noetrium:<exact-source-sha>"
    docker compose -f deploy/compose.yaml -f deploy/environments/minecraft/compose.yaml build platform-runtime
    docker compose -f deploy/compose.yaml -f deploy/environments/minecraft/compose.yaml run --rm platform-runtime environment-doctor minecraft

The same pattern applies to `embodied`, `gui`, `web`, and `software`. `text_world` intentionally uses the base image directly.

Environment profiles are reusable deployment capabilities. A downstream research repository may inherit or compose them, but Noetrium must never grow a benchmark layer or paper/reproduction layer beneath them.
