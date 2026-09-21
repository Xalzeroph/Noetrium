
ARG PLATFORM_BASE_IMAGE=noetrium:local
ARG JAVA_RUNTIME_IMAGE=eclipse-temurin:21-jre-jammy
FROM ${JAVA_RUNTIME_IMAGE} AS java-runtime

FROM ${PLATFORM_BASE_IMAGE}

ARG NODE_VERSION=22.22.2
ENV JAVA_HOME=/opt/java/openjdk \
    MC_DATA_DIR=/var/lib/minecraft \
    NOETRIUM_ENVIRONMENT_PROFILE=minecraft \
    PATH=/opt/java/openjdk/bin:/usr/local/bin:$PATH

USER root
COPY --from=java-runtime /opt/java/openjdk /opt/java/openjdk

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN cd /tmp \
    && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" \
    && grep " node-v${NODE_VERSION}-linux-x64.tar.xz$" SHASUMS256.txt | sha256sum -c - \
    && tar -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" --strip-components=1 -C /usr/local \
    && rm -f "node-v${NODE_VERSION}-linux-x64.tar.xz" SHASUMS256.txt

RUN bridge="$(python -c 'from pathlib import Path; import noetrium_platform; print(Path(noetrium_platform.__file__).resolve().parent / "capabilities/environment/minecraft/providers/assets/mineflayer_bridge")')" \
    && test -f "$bridge/package-lock.json" \
    && npm --prefix "$bridge" ci --omit=dev --ignore-scripts \
    && mkdir -p "$MC_DATA_DIR" \
    && chown -R platform:platform "$MC_DATA_DIR"

USER platform
CMD ["environment-doctor", "minecraft"]
