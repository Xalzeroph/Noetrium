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

## Host contract

The deployment host requires Docker (including Compose) and access to its Docker daemon. Host Python is deliberately **not** part of the deployment contract. Release qualification, provenance verification, and environment-image orchestration execute in the disposable control-plane image defined by `deploy/bootstrap/Dockerfile`.

The canonical host entrypoint is therefore:

    ./deploy/build-environments.sh list
    ./deploy/build-environments.sh show minecraft
    ./deploy/build-environments.sh validate
    ./deploy/build-environments.sh build --profiles minecraft embodied gui web software text_world

`NOETRIUM_BOOTSTRAP_IMAGE` may select the local control-plane image tag. `NOETRIUM_DOCKER_CLI_IMAGE` may select an organization-approved Docker CLI source or registry mirror without changing platform source. `NOETRIUM_BUILD_WORK_ROOT` selects the writable build/runtime evidence root. Registry policy belongs to deployment configuration; benchmark or paper identity never belongs here.

Runtime parent images follow the same rule. The canonical identities remain `python:3.12-slim-bookworm` and `eclipse-temurin:21-jre-jammy`, while deployment may select alternate registry sources with `--python-runtime-image` and `--java-runtime-image`. The build receipt records both canonical and actual source identities, including Docker image metadata when materialized. No registry mirror is hard-coded into the platform.

The bootstrap resolves the daemon endpoint from `DOCKER_HOST` or the active Docker context rather than assuming a rootful `/var/run/docker.sock`. Unix-socket endpoints, including rootless Docker sockets, are mounted at their existing absolute path; non-TLS TCP endpoints are forwarded without a host socket mount. TLS/SSH daemon transports remain explicit deployment integrations because the bootstrap must not silently copy host credentials into its control-plane container.

The bootstrap mounts the checkout read-only and preserves its absolute host path inside the control-plane container. This is required because the control plane talks to the host Docker daemon: daemon-side build contexts and Compose bind mounts must resolve the same paths. Only the dedicated build/runtime root is writable.

## Base image

The base image is distribution-bound and must not be rebuilt directly from the mutable checkout. The canonical Docker-only entrypoint above performs the qualification path in the control-plane container:

release source
→ qualified wheel + distribution evidence
→ exact container context
→ evidence-bound base image
→ provenance verification
→ reusable environment images
→ profile doctors

`scripts/build_environment_images.py` remains the Python implementation behind that control-plane boundary. It is not a host-Python contract.

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

The build command creates the evidence-bound base image only when the exact source-SHA image is missing (or `--rebuild` is requested). On a cache hit it re-verifies the embedded wheel and installed wheel RECORD, then reuses the image. Each missing environment image is built independently and every requested profile is doctor-checked. Build scratch state is isolated from the reusable runtime-state root, so repeated deployments do not wipe environment state. `text_world` maps directly to the verified base image and does not create a redundant image.

Environment profiles are reusable deployment capabilities. A downstream research repository may inherit or compose them, but Noetrium must never grow a benchmark layer or paper/reproduction layer beneath them.
