
ARG PLATFORM_BASE_IMAGE=noetrium:local
ARG JAVA_RUNTIME_IMAGE=eclipse-temurin:21-jre-jammy
ARG NODE_RUNTIME_IMAGE=node:22.22.2-bookworm-slim
FROM ${JAVA_RUNTIME_IMAGE} AS java-runtime
FROM ${NODE_RUNTIME_IMAGE} AS node-runtime

FROM ${PLATFORM_BASE_IMAGE}

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
    NOETRIUM_ENVIRONMENT_PROFILE=minecraft \
    PATH=/opt/java/openjdk/bin:/usr/local/bin:$PATH

USER root
RUN mkdir -p /usr/local/lib/noetrium/environment-doctor.d
COPY deploy/environments/minecraft/doctor.sh /usr/local/lib/noetrium/environment-doctor.d/minecraft
RUN chmod 0755 /usr/local/lib/noetrium/environment-doctor.d/minecraft
COPY --from=java-runtime /opt/java/openjdk /opt/java/openjdk
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version \
    && npm --version

RUN bridge="$(python -c 'from pathlib import Path; import noetrium_platform; print(Path(noetrium_platform.__file__).resolve().parent / "capabilities/environment/minecraft/providers/assets/mineflayer_bridge")')" \
    && test -f "$bridge/package-lock.json" \
    && npm --prefix "$bridge" ci --omit=dev --ignore-scripts \
    && mkdir -p "$MC_DATA_DIR" \
    && chown -R platform:platform "$MC_DATA_DIR"

USER platform
CMD ["environment-doctor", "minecraft"]
