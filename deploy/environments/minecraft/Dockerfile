ARG PLATFORM_ENVIRONMENT_BASE_IMAGE=noetrium-env-base:local
ARG JAVA_RUNTIME_IMAGE=eclipse-temurin:21-jre-jammy
ARG NODE_RUNTIME_IMAGE=node:22.22.2-bookworm-slim
FROM ${JAVA_RUNTIME_IMAGE} AS java-runtime
FROM ${NODE_RUNTIME_IMAGE} AS node-runtime
WORKDIR /opt/noetrium-mineflayer
COPY noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/package.json ./
COPY noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM ${PLATFORM_ENVIRONMENT_BASE_IMAGE}

ARG NOETRIUM_ENVIRONMENT_PROFILE_ID
ARG NOETRIUM_ENVIRONMENT_CATEGORY_ID
ARG NOETRIUM_ENVIRONMENT_PROFILE_REVISION
ARG NOETRIUM_ENVIRONMENT_BUILD_INPUT_DIGEST
LABEL org.opencontainers.image.noetrium.environment.profile-id="${NOETRIUM_ENVIRONMENT_PROFILE_ID}" \
      org.opencontainers.image.noetrium.environment.category-id="${NOETRIUM_ENVIRONMENT_CATEGORY_ID}" \
      org.opencontainers.image.noetrium.environment.profile-revision="${NOETRIUM_ENVIRONMENT_PROFILE_REVISION}" \
      org.opencontainers.image.noetrium.environment.build-input.sha256="${NOETRIUM_ENVIRONMENT_BUILD_INPUT_DIGEST}"

ENV JAVA_HOME=/opt/java/openjdk \
    MC_DATA_DIR=/var/lib/minecraft \
    MC_BRIDGE_DIR=/opt/noetrium-environments/minecraft/bridge \
    NOETRIUM_ENVIRONMENT_PROFILE=minecraft \
    PATH=/opt/java/openjdk/bin:/usr/local/bin:$PATH

USER root
COPY --link --chmod=0755 deploy/environments/minecraft/doctor.sh /usr/local/lib/noetrium/environment-doctor.d/minecraft
COPY --link --from=java-runtime /opt/java/openjdk /opt/java/openjdk
COPY --link --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --link --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --link --from=node-runtime /opt/noetrium-mineflayer/node_modules /opt/noetrium-mineflayer/node_modules
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/package.json /opt/noetrium-environments/minecraft/bridge/package.json
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/package-lock.json /opt/noetrium-environments/minecraft/bridge/package-lock.json
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/action_recovery.js /opt/noetrium-environments/minecraft/bridge/action_recovery.js
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/bridge.js /opt/noetrium-environments/minecraft/bridge/bridge.js
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/combat.js /opt/noetrium-environments/minecraft/bridge/combat.js
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/interactions.js /opt/noetrium-environments/minecraft/bridge/interactions.js
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/inventory.js /opt/noetrium-environments/minecraft/bridge/inventory.js
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/movement.js /opt/noetrium-environments/minecraft/bridge/movement.js
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/resources.js /opt/noetrium-environments/minecraft/bridge/resources.js
COPY --link noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/runtime.js /opt/noetrium-environments/minecraft/bridge/runtime.js
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version \
    && npm --version

RUN bridge="$MC_BRIDGE_DIR" \
    && test -f "$bridge/package-lock.json" \
    && ln -s /opt/noetrium-mineflayer/node_modules "$bridge/node_modules" \
    && mkdir -p "$MC_DATA_DIR" \
    && chown -R platform:platform "$MC_DATA_DIR"

USER platform
CMD ["environment-doctor", "minecraft"]
